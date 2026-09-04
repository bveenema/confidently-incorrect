# Confidently Incorrect

> Yahoo fantasy football team managed by a five-vendor LLM council.
> Decision reasoning published; personas graded against counterfactuals.

## Tech Stack

- **Languages:** Python 3.12 (3.11 is enough for current unit tests)
- **Frameworks:** FastAPI admin console (not built yet); static log site later
- **Platforms/Targets:** Podman containers; Vultr VPS on systemd timers; local workstation for the draft assistant

## Tooling

- **Package manager:** pip / `pyproject.toml`
- **Build system:** Makefile (`make test`, `make lint`, `make fmt`, `make build`)
- **Containers:** Podman (`Containerfile`, `compose.yml`); image tag `ci:<shortsha>`
- **CI/CD:** none — PRs and squash merge to main; `deploy.sh` later (D-70)
- **Linting/Formatting:** ruff, mypy
- **Testing:** pytest

## Architecture

`src/` on `PYTHONPATH`: `yahoo`, `council`, `db`, `data`, `web`. Dual
knowledge base (SQLite ledger + markdown notes) lives on the volume at
`/srv/ci/`, **outside** this git tree. MQTT UNS (`uns.md`) is the
current-state bus; `kb.db` is the record.

### Directory Layout

- `.ai/rules.md` — binding agent rules
- `.ai/workflows/` — Hephaestus specs (vendored)
- `architecture.md`, `implementation.md`, `followups.md`, `council-prompts.md`, `uns.md` — spec
- `src/` — application packages (scaffold only)
- `infra/mosquitto/` — local broker config
- `assets/` — logo and admin mockup
- `claude_dump/` — archived conversation; not live spec

### Key Entry Points

- `CLAUDE.md` — Development Commands for Hephaestus `/ship`
- `Makefile` — test, lint, fmt, build, dry-run, run
- `compose.yml` — engine + mosquitto, `CI_STATE_DIR` → `/srv/ci`

## Development

### Setup

`python -m venv .venv`, `pip install -e ".[dev]"`, `make test`. Set
`CI_STATE_DIR` to a directory outside the worktree.

### Common Commands

| Command | Description |
|---|---|
| `make test` | Unit tests |
| `make lint` | ruff check + mypy |
| `make fmt` | ruff format |
| `make build` | podman build, tag `ci:<sha>` |

### Testing

pytest under `tests/`. Integration tests (`make test-integration`) need
live credentials and are empty until those clients exist.

## Project Context

Work league, draft 6 Sep 2026. Full autonomy from week 1. Entertainment
> decision quality > win rate > experiment integrity; the council always
tries to win. Runtime state must never sit inside the git working
directory.

## Conventions

- Never hardcode league-derived values.
- Never let model output reach Yahoo unvalidated.
- Never write real manager or team names into the ledger, notes, logs,
  prompts, or MQTT payloads.
- Never touch the operator's real `$CI_STATE_DIR` / `/srv/ci/` unless
  the user names the file and asks (D-90). Tests use a temp dir.
- Timezone is `America/New_York`.
- After week 1: no deploys Thu 17:00–Mon 23:59 ET; persona prompts frozen.
- Cursor has no worktree isolation — serialize file-modifying coder tasks.

## AI Context

- [`.ai/rules.md`](../.ai/rules.md) — binding rules
- [`.cursor/rules/project.mdc`](rules/project.mdc) — always-apply pointer
- [`.cursor/rules/hephaestus.mdc`](rules/hephaestus.mdc) — Hephaestus adapters
