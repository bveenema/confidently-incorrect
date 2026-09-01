# Confidently Incorrect

A Yahoo fantasy football team managed entirely by a council of LLM
personas from five vendors. Decision reasoning is published; every
persona's calls are graded against counterfactual outcomes.

**Draft: Sunday 6 September 2026, 20:00 EDT.**

Ben knows nothing about football. That is the premise, not a problem
to solve.

## Spec (read these first)

| File | What it holds |
|---|---|
| [`.ai/rules.md`](.ai/rules.md) | Binding rules for anyone implementing |
| [`architecture.md`](architecture.md) | Design decisions and the numbered log (D-1…) |
| [`implementation.md`](implementation.md) | Build order, critical path, league facts |
| [`followups.md`](followups.md) | Open verifications |
| [`council-prompts.md`](council-prompts.md) | Persona prompts and the brief schema |
| [`uns.md`](uns.md) | MQTT Unified Namespace (current-state bus) |
| [`CLAUDE.md`](CLAUDE.md) | Commands Hephaestus `/ship` reads |

The conversation that produced the spec is archived in `claude_dump/`.
Do not treat that folder as live documentation.

## Setup

Needs Python 3.12+ (3.11 works for unit tests), [Make](https://gnuwin32.sourceforge.net/packages/make.htm)
on PATH, and [Podman](https://podman.io/) for the container targets.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate
pip install -e ".[dev]"
make test
make lint
```

Runtime state lives **outside** the git tree (D-72). On this workstation
set `CI_STATE_DIR` to something like `%USERPROFILE%\.local\share\ci`.
Inside the container that directory is mounted at `/srv/ci`.

```powershell
$env:CI_STATE_DIR = "$env:USERPROFILE\.local\share\ci"
New-Item -ItemType Directory -Force -Path $env:CI_STATE_DIR | Out-Null
podman compose up --build
```

If the Windows/WSL volume mount fails, the real runtime is a Linux VPS
where `/srv/ci/` is a native path. Do not spend draft week debugging
the mount.

### Yahoo OAuth (one-time)

Fantasy Sports API access is **approval-gated** (follow-up A-12). Apply
at [sports.yahoo.com/developer/access](https://sports.yahoo.com/developer/access/)
before expecting any live call to work. Do not delete an existing App
ID — new registrations no longer offer the Fantasy Sports permission.

Once Yahoo has bound the app:

1. Write `$CI_STATE_DIR/tokens/yahoo-app.json` with `client_id` and
   `client_secret`. Never put that file in the repo or the image.
2. `python -m yahoo authorize` — opens the `oob` URL, paste the code,
   token is written to `$CI_STATE_DIR/tokens/yahoo.json`.
3. `python -m yahoo smoke` — reads own team, league settings, and
   roster. Refresh after expiry is unattended.

A 401 means the refresh token is dead and needs a browser. A 403
means the access program, not a bad token.

## Make targets

| Target | What it does |
|---|---|
| `make test` | Unit tests |
| `make test-integration` | Live APIs (needs `CI_STATE_DIR` with Yahoo token files) |
| `make lint` | ruff + mypy |
| `make fmt` | ruff format |
| `make build` | `podman build`, tagged `ci:<shortsha>` |
| `make dry-run` | Full pipeline, no Yahoo writes (stub until that issue ships) |
| `make run TASK=…` | Single task locally (stub until that issue ships) |

Cursor has no worktree isolation. File-modifying coder tasks stay
serialized. Hephaestus adapters (v2.2.0,
`a121813a12f975ec710ef527e15e7627a10bdeb2`) live in `.cursor/commands/`
(`/autopilot`, `/ship`). MIT license: `.ai/HEPHAESTUS-LICENSE`. After
week 1, deploys go through `deploy.sh` and PRs with squash merge to
`main` (D-70). This repo's first commit is a bootstrap exception to
that rule.

Team art is in [`assets/`](assets/).
