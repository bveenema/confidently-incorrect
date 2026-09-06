from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from council import (
    CouncilConfigError,
    CouncilRunError,
    CouncilValidationError,
    OpenRouterClient,
    load_credentials,
    run_council,
    validate_brief,
    validate_gm,
)
from council.__main__ import main
from council.credentials import DEFAULT_MODELS, credentials_path, model_for
from council.openrouter import _completion_body
from council.paths import state_dir
from council.prompts import gm_system, specialist_system
from council.schema import canonicalize_player_key, parse_json_object
from db import connect, migrate

POOL = [f"yahoo:{i}" for i in range(1, 8)]
PERSONA_FOR_MODEL = {
    model: name
    for name, model in DEFAULT_MODELS.items()
    if name not in {"maddox_draft", "lasso"}
}
PERSONA_FOR_MODEL[DEFAULT_MODELS["maddox_draft"]] = "maddox"


def _write_key(root: Path, key: str = "test-key") -> None:
    path = credentials_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"api_key": key}), encoding="utf-8")


def _recs(keys: list[str] | None = None) -> list[dict[str, object]]:
    chosen = keys or POOL[:5]
    return [
        {
            "action": "draft",
            "player_key": key,
            "player_name": f"Player {key}",
            "slot": None,
            "priority": index + 1,
        }
        for index, key in enumerate(chosen)
    ]


def _brief(persona: str, keys: list[str] | None = None) -> dict[str, object]:
    return {
        "persona": persona,
        "decision_type": "draft",
        "recommendations": _recs(keys),
        "confidence": 0.55,
        "reasoning": "Best available on this board.",
        "dissent": None,
        "voice_line": "Take him.",
    }


def _gm(keys: list[str] | None = None) -> dict[str, object]:
    chosen = keys or POOL[:5]
    return {
        "decision_type": "draft",
        "final_actions": [
            {"action": "draft", "player_key": key, "slot": None} for key in chosen
        ],
        "adopted_from": ["brand"],
        "overruled": ["taco"],
        "override_reason": "Brand's EV.",
        "unanimous_override": False,
        "rationale": "Take the top five on the board.",
        "voice_line": "That's football.",
    }


def _ok_bodies() -> dict[str, object]:
    return {
        "belichuk": _brief("belichuk"),
        "brand": _brief("brand"),
        "taco": _brief("taco"),
        "maddox": _gm(),
    }


def _handler(
    bodies: dict[str, object],
    *,
    status: dict[str, int] | None = None,
    seen: list[str] | None = None,
    systems: list[str] | None = None,
):
    codes = status or {}

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        model = payload["model"]
        persona = PERSONA_FOR_MODEL.get(model, "unknown")
        if seen is not None:
            seen.append(persona)
        if systems is not None:
            messages = payload.get("messages") or []
            if messages:
                systems.append(str(messages[0].get("content", "")))
        code = codes.get(persona, 200)
        if code >= 400:
            return httpx.Response(code, json={"error": "upstream"})
        body = bodies[persona]
        content = body if isinstance(body, str) else json.dumps(body)
        return httpx.Response(
            200,
            json={
                "model": model,
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "cost": 0.002,
                },
            },
        )

    return handle


def _client(root: Path, handler) -> OpenRouterClient:
    _write_key(root)
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenRouterClient(root, http=http)


def test_gemini_keeps_required_reasoning() -> None:
    gemini = _completion_body("google/gemini-2.5-pro", "sys", "user")
    assert "reasoning" not in gemini
    claude = _completion_body("anthropic/claude-sonnet-4.5", "sys", "user")
    assert claude["reasoning"] == {"enabled": False, "effort": "none"}
    other = _completion_body("openai/gpt-4o", "sys", "user")
    assert "reasoning" not in other


def test_draft_gm_uses_flash_slug(tmp_path: Path) -> None:
    _write_key(tmp_path)
    creds = load_credentials(tmp_path)
    assert model_for("maddox", creds) == "google/gemini-2.5-pro"
    assert model_for("maddox", creds, decision_type="lineup") == (
        "google/gemini-2.5-pro"
    )
    assert model_for("maddox", creds, decision_type="draft") == (
        "google/gemini-2.5-flash"
    )


def test_placeholder_key_rejected(tmp_path: Path) -> None:
    _write_key(tmp_path, "REPLACE_ME")
    with pytest.raises(CouncilConfigError, match="api_key"):
        load_credentials(tmp_path)


def test_parse_json_strips_fences() -> None:
    raw = parse_json_object('```json\n{"persona": "brand"}\n```')
    assert raw["persona"] == "brand"


def test_canonicalize_yahoo_api_key() -> None:
    pool = {"yahoo:12345"}
    assert canonicalize_player_key("461.p.12345", pool) == "yahoo:12345"
    assert canonicalize_player_key("12345", pool) == "yahoo:12345"
    assert canonicalize_player_key("yahoo:12345", pool) == "yahoo:12345"
    assert canonicalize_player_key("yahoo:999", pool) is None


def test_brief_stamps_persona_when_model_echoes_the_wrong_handle() -> None:
    raw = _brief("belichuk")
    brief = validate_brief(
        raw, expected_persona="brand", decision_type="draft", pool=set(POOL)
    )
    assert brief.persona == "brand"


def test_brief_stamps_persona_when_model_omits_it() -> None:
    raw = _brief("brand")
    del raw["persona"]
    brief = validate_brief(
        raw, expected_persona="taco", decision_type="draft", pool=set(POOL)
    )
    assert brief.persona == "taco"


def test_brief_rejects_unknown_player_key() -> None:
    raw = _brief("brand", ["yahoo:999"])
    with pytest.raises(CouncilValidationError, match="unknown"):
        validate_brief(
            raw, expected_persona="brand", decision_type="draft", pool=set(POOL)
        )


def test_draft_brief_requires_five() -> None:
    raw = _brief("brand", POOL[:3])
    with pytest.raises(CouncilValidationError, match="at least 5"):
        validate_brief(
            raw, expected_persona="brand", decision_type="draft", pool=set(POOL)
        )


def test_successful_draft_writes_runs_and_briefs(tmp_path: Path) -> None:
    seen: list[str] = []
    client = _client(tmp_path, _handler(_ok_bodies(), seen=seen))
    result = run_council(
        state_dir=tmp_path,
        packet={"pick": 1},
        pool=POOL,
        decision_type="draft",
        season_id="2026",
        client=client,
    )
    assert result.failure_mode is None
    assert {brief.persona for brief in result.briefs} == {
        "belichuk",
        "brand",
        "taco",
    }
    assert result.decision is not None
    assert result.absent == ()
    assert set(seen[:3]) == {"belichuk", "brand", "taco"}
    assert seen[-1] == "maddox"
    with connect(tmp_path) as conn:
        run = conn.execute(
            "SELECT decision_type, failure_mode, absent_personas FROM runs"
        ).fetchone()
        assert run == ("draft", None, "")
        rows = conn.execute(
            "SELECT persona, model, tokens, cost FROM briefs ORDER BY persona"
        ).fetchall()
        personas = {row[0] for row in rows}
        assert personas == {"belichuk", "brand", "taco", "maddox"}
        assert all(row[2] == 15 and row[3] == 0.002 for row in rows)
        decisions = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    assert decisions == 1


def test_missing_specialist_does_not_block(tmp_path: Path) -> None:
    bodies = _ok_bodies()
    client = _client(tmp_path, _handler(bodies, status={"taco": 503}))
    result = run_council(
        state_dir=tmp_path,
        packet={"pick": 1},
        pool=POOL,
        decision_type="draft",
        season_id="2026",
        client=client,
    )
    assert result.absent == ("taco",)
    assert {brief.persona for brief in result.briefs} == {"belichuk", "brand"}
    assert result.decision is not None
    with connect(tmp_path) as conn:
        absent = conn.execute("SELECT absent_personas FROM runs").fetchone()[0]
        personas = {row[0] for row in conn.execute("SELECT persona FROM briefs")}
        reason = conn.execute(
            "SELECT reasoning FROM briefs WHERE persona = 'taco'"
        ).fetchone()[0]
    assert absent == "taco"
    assert "taco" in personas
    assert reason and "OpenRouter HTTP 503" in reason


def test_malformed_brief_rejected_not_retried(tmp_path: Path) -> None:
    seen: list[str] = []
    bodies = _ok_bodies()
    bodies["brand"] = "not-json"
    client = _client(tmp_path, _handler(bodies, seen=seen))
    result = run_council(
        state_dir=tmp_path,
        packet={"pick": 1},
        pool=POOL,
        decision_type="draft",
        season_id="2026",
        client=client,
    )
    assert result.rejected == ("brand",)
    assert "brand" in result.absent
    assert seen.count("brand") == 1
    with connect(tmp_path) as conn:
        row = conn.execute(
            "SELECT recommendations, tokens, cost, reasoning FROM briefs "
            "WHERE persona = 'brand'"
        ).fetchone()
    assert row[0] is None
    assert row[1] == 15
    assert row[2] == 0.002
    assert "JSON" in (row[3] or "")


def test_missing_gm_fails_and_writes_failure_mode(tmp_path: Path) -> None:
    client = _client(tmp_path, _handler(_ok_bodies(), status={"maddox": 500}))
    with pytest.raises(CouncilRunError, match="gm_missing"):
        run_council(
            state_dir=tmp_path,
            packet={"pick": 1},
            pool=POOL,
            decision_type="draft",
            season_id="2026",
            client=client,
        )
    with connect(tmp_path) as conn:
        mode = conn.execute("SELECT failure_mode FROM runs").fetchone()[0]
        count = conn.execute("SELECT COUNT(*) FROM briefs").fetchone()[0]
        decisions = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    assert mode == "gm_missing"
    assert count == 4
    assert decisions == 0
    with connect(tmp_path) as conn:
        reason = conn.execute(
            "SELECT reasoning FROM briefs WHERE persona = 'maddox'"
        ).fetchone()[0]
    assert reason and "OpenRouter HTTP 500" in reason


def test_invalid_gm_writes_failure_mode(tmp_path: Path) -> None:
    bodies = _ok_bodies()
    bodies["maddox"] = {"decision_type": "draft"}
    client = _client(tmp_path, _handler(bodies))
    with pytest.raises(CouncilRunError, match="gm_invalid"):
        run_council(
            state_dir=tmp_path,
            packet={"pick": 1},
            pool=POOL,
            decision_type="draft",
            season_id="2026",
            client=client,
        )
    with connect(tmp_path) as conn:
        mode = conn.execute("SELECT failure_mode FROM runs").fetchone()[0]
    assert mode == "gm_invalid"


def test_bad_player_key_rejects_whole_brief(tmp_path: Path) -> None:
    bodies = _ok_bodies()
    bodies["belichuk"] = _brief("belichuk", ["yahoo:999"] + POOL[:4])
    client = _client(tmp_path, _handler(bodies))
    result = run_council(
        state_dir=tmp_path,
        packet={"pick": 1},
        pool=POOL,
        decision_type="draft",
        season_id="2026",
        client=client,
    )
    assert "belichuk" in result.rejected
    assert result.decision is not None


def test_cli_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_key(tmp_path)
    packet = tmp_path / "packet.json"
    pool = tmp_path / "pool.json"
    packet.write_text(json.dumps({"pick": 1}), encoding="utf-8")
    pool.write_text(json.dumps(POOL), encoding="utf-8")
    transport = httpx.MockTransport(_handler(_ok_bodies()))

    class Injected(OpenRouterClient):
        def __init__(self, state_dir: Path, http=None, creds=None) -> None:
            super().__init__(
                state_dir,
                http=httpx.Client(transport=transport),
                creds=creds,
            )

    monkeypatch.setattr("council.orchestrator.OpenRouterClient", Injected)
    code = main(
        [
            "run",
            "--packet",
            str(packet),
            "--pool",
            str(pool),
            "--state-dir",
            str(tmp_path),
            "--season",
            "2026",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert out.startswith("ok: run ")
    assert "draft" in out


def test_unset_ci_state_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI_STATE_DIR", raising=False)
    monkeypatch.setattr("council.paths._LINUX_DEFAULT", Path("/nonexistent-ci-state"))
    with pytest.raises(CouncilConfigError, match="CI_STATE_DIR"):
        state_dir()


def test_validate_gm_unknown_key() -> None:
    raw = _gm(["yahoo:999"] + POOL[:4])
    with pytest.raises(CouncilValidationError, match="live pool"):
        validate_gm(raw, decision_type="draft", pool=set(POOL))


def test_packet_team_count_reaches_prompts(tmp_path: Path) -> None:
    systems: list[str] = []
    client = _client(tmp_path, _handler(_ok_bodies(), systems=systems))
    run_council(
        state_dir=tmp_path,
        packet={"pick": 1, "team_count": 8},
        pool=POOL,
        decision_type="draft",
        season_id="2026",
        client=client,
    )
    assert systems
    assert all("8-team" in text for text in systems)
    assert all("12-team" not in text for text in systems)
    gm_prompts = [
        text for text in systems if "You make the final call on every decision" in text
    ]
    assert gm_prompts
    assert all("You advise. You do not decide." not in text for text in gm_prompts)


def test_internal_error_marks_failed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, _handler(_ok_bodies()))

    def boom(*_args, **_kwargs):
        raise RuntimeError("ledger write failed")

    monkeypatch.setattr("council.orchestrator.insert_brief_row", boom)
    with pytest.raises(RuntimeError, match="ledger write failed"):
        run_council(
            state_dir=tmp_path,
            packet={"pick": 1},
            pool=POOL,
            decision_type="draft",
            season_id="2026",
            client=client,
        )
    with connect(tmp_path) as conn:
        mode = conn.execute("SELECT failure_mode FROM runs").fetchone()[0]
    assert mode == "internal_error"


def test_gm_system_is_not_the_specialist_preamble() -> None:
    gm = gm_system(team_count=8)
    specialist = specialist_system("brand", team_count=8)
    assert "You advise. You do not decide." not in gm
    assert "You make the final call" in gm
    assert "8-team" in gm
    assert "You advise. You do not decide." in specialist
    assert "12-team" not in gm
    assert "12-team" not in specialist


def test_migrate_still_idempotent(tmp_path: Path) -> None:
    migrate(tmp_path)
    migrate(tmp_path)
    with connect(tmp_path) as conn:
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "runs" in names
