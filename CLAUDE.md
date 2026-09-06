# CLAUDE.md

Project configuration for AI coding agents. Hephaestus workflows read
this file at runtime — `## Development Commands` is the section they
require.

## Project

**Confidently Incorrect** — a Yahoo fantasy football team managed
entirely by a council of LLM personas from five vendors, with published
decision reasoning and per-persona outcome attribution.

Python, containerized with Podman, deployed to a Vultr VPS on systemd
timers.

**Hard deadline: draft Sunday 6 September 2026, 20:00 EDT.**

## Read these first

Binding project rules live in `.ai/rules.md`. Read it before any
non-trivial change — it governs documentation duties, mid-season change
control, deploy discipline, and a list of things that must never be
done.

| Document | What it holds |
|---|---|
| `.ai/rules.md` | Binding agent rules. Read first. |
| `architecture.md` | Design decisions and the numbered decision log (D-1…) |
| `implementation.md` | Build order, critical path, league facts |
| `followups.md` | Open verifications with deadlines and consequences |
| `council-prompts.md` | Persona prompts and the brief schema |
| `uns.md` | MQTT Unified Namespace — current-state bus |

Note: `.ai/rules.md` is this project's own file. Hephaestus also uses
`.ai/` for its workflow specs — the two coexist; do not merge them.

## Development Commands

```bash
# Test
make test                 # unit tests
make test-integration     # hits live APIs, requires credentials

# Lint and format
make lint                 # ruff check + mypy
make fmt                  # ruff format

# Build
make build                # podman build, tags by short SHA

# Run
make dry-run              # full pipeline, no writes to Yahoo
make run TASK=lineup      # single task locally
```

Quality gates for `/ship`: `make lint` and `make test` must pass.
`make dry-run` must complete for any change touching a submission path.

## Constraints agents must respect

- **Never hardcode league-derived values.** Team count, scoring table,
  roster slots, playoff structure, trade deadline, waiver rules are all
  read at runtime — from `$CI_STATE_DIR/league-settings.json` until
  A-12 unblocks D-47, then from the Yahoo API (D-83). The league is
  expected to grow from 8 teams and settings can change mid-season.
- **Never let model output reach the Yahoo API unvalidated.** Guardrails
  are deterministic code between the GM decision and execution.
- **Never write real manager or team names** into `kb.db`, `notes/`,
  logs, or any model prompt. Pseudonymization happens at ingest.
- **Runtime state** is `$CI_STATE_DIR` on the workstation and
  `/srv/ci/` on the VPS — the same store, outside the git tree. No git
  command may reach it. Agents must not read secrets from it into the
  session, and must not create, overwrite, delete, or repair files
  there unless the user explicitly names the file and asks. Unit tests
  use a temp dir only. See `.ai/rules.md` §3.1 / §4.
- **Timezone is `America/New_York`** everywhere.
- **Deploys are manual** via `deploy.sh`. `/ship` merges to main; it
  does not deploy. Do not wire deployment into the ship phase.
- **After week 1 begins**, no deploys Thu 17:00 – Mon 23:59 ET, and
  persona prompts are frozen for the season. See `.ai/rules.md` §3.
- **GitHub writing is two sections** (`## What this means` then
  `## Details`) on every PR, issue, comment, and issue/PR reply.
  See `.ai/rules.md` §9.

## Worktrees

Cursor has no worktree isolation, so file-modifying coder tasks are
serialized regardless of what the plan says.

Contention hotspots — issues touching these should not be planned in the
same wave:

- `src/yahoo/` — the API client, touched by nearly every feature
- `src/council/` — orchestrator and schema
- `src/db/schema.sql` — migrations serialize by nature
- `strategy.json` schema — knob additions ripple into the admin console

## Issue conventions

Labels: `milestone:draft`, `milestone:week1`, `milestone:season`,
`area:yahoo`, `area:council`, `area:data`, `area:web`, `area:infra`,
`blocked`, `verification`.

Every issue needs acceptance criteria. Issues tagged `verification`
correspond to a row in `followups.md` — resolving one means writing the
answer into that row, not just closing the issue.
