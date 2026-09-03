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
2. `python -m yahoo authorize` — prints the `oob` URL, paste the code,
   token is written to `$CI_STATE_DIR/tokens/yahoo.json`.
3. `python -m yahoo smoke` — reads own team, league settings, and
   roster. Refresh after expiry is unattended.

A 401 that survives one refresh means the refresh token is dead and
needs a browser. A 403 means the access program, not a bad token.

### League settings (draft path)

Yahoo Fantasy ingest is blocked until the access program approves the
app (A-12 / D-47). Until then the scoring engine and draft tool read
`$CI_STATE_DIR/league-settings.json`. Nothing league-derived is a
constant in source (D-83).

1. Copy [`templates/league-settings.json`](templates/league-settings.json)
   to `$CI_STATE_DIR/league-settings.json`.
2. Replace every fake value from the Yahoo league settings page
   (League → Settings). The template's `99`s, `example-*` labels,
   and inverted booleans (`fractional_points`, `draft_pick_trades`,
   `ir_adds_from_waivers`) are intentional — leaving them will
   silently score or constrain the wrong game.
3. `python -m data validate-league-settings` — exits 0 if the file is
   usable, or prints every problem and exits 1. `--path` points at
   another file (including the template).

If the file is missing or invalid the process exits non-zero. There
are no built-in 8-team or standard-scoring fallbacks. Edit the file
again if the league grows; the loader does not care whether
`team_count` is 8 or 12.

### FantasyPros (projections)

HOF production key. Copy
[`templates/fantasypros.json`](templates/fantasypros.json) to
`$CI_STATE_DIR/tokens/fantasypros.json` and replace `api_key`. Never
put the real key in the repo.

`python -m data fantasypros-smoke` reads week-0 and week-1 projections,
RB consensus rankings (`rank_std` for D-21), injuries, and news.
Stat keys are mapped onto the scoring-engine slugs; provider
`points*` totals are dropped. Exits 1 if FantasyPros truncates the
pool (`tier=free`). After upgrading to HOF, mint a production key at
https://secure.fantasypros.com/api-keys if smoke still reports
10-player pages. Attribution string is `data.ATTRIBUTION`.

### Tank01 (secondary projections)

RapidAPI Basic is enough to validate; Pro ($10/mo, 1000 req/day) is
the season plan (D-20). Copy
[`templates/tank01.json`](templates/tank01.json) to
`$CI_STATE_DIR/tokens/tank01.json` and replace `api_key` with the
RapidAPI application key. Subscribe to **Tank01 NFL Live In-Game**
(not Tank01 Fantasy Stats — that product is NBA).

`python -m data tank01-smoke` reads season-long and week-1 projections,
injuries (from the player list), recent news, and implied team totals
derived from betting lines for `--odds-date YYYYMMDD` (default today
ET). Provider `fantasyPointsDefault` totals are dropped; nested
Passing/Rushing/Receiving/Kicking/DST stats map onto engine slugs.
Kicker lines are `fg`/`fga`/`pat_*` only (no distance bands). DST has
no return yards. Attribution is `data.TANK01_ATTRIBUTION`.

| JSON field | Yahoo settings page |
|---|---|
| `team_count` | Number of teams |
| `roster_slots` | Roster positions and counts |
| `scoring.fractional_points` | Fractional Points |
| `scoring.negative_points` | Negative Points (store the label; A-6 is still open) |
| `scoring.categories` | Every scoring line. `points` is the fantasy value; `per` is stat units per point (yards); `range` is an inclusive `[min, max]` band (DST points/yards allowed) |
| `trade_deadline` | Trade deadline (`YYYY-MM-DD`, America/New_York) |
| `waiver` | Waiver type, days, and process |
| `playoff` | Playoff teams and weeks |
| `draft` | Rounds and draft type |

Stat slugs `data.fantasy_points` consumes: `pass_cmp`,
`pass_att`, `pass_yd`, `pass_td`, `pass_int`, `rush_att`, `rush_yd`,
`rush_td`, `rec`, `rec_yd`, `rec_td`, `fum`, `fum_lost`, `two_pt`,
`fg_0_19`…`fg_60_plus`, `fg_miss_0_19`…`fg_miss_60_plus`, `pat_made`,
`pat_miss`, `dst_sack`, `dst_int`, `dst_fum_rec`, `dst_td`,
`dst_safety`, `dst_blk`, `dst_return_yd`, `dst_pts_allowed`,
`dst_yds_allowed`. Extra well-formed categories are kept. Copy every
Yahoo scoring line; omitted stats score zero later.

## Make targets

| Target | What it does |
|---|---|
| `make test` | Unit tests |
| `make test-integration` | Live APIs (needs `CI_STATE_DIR` with Yahoo and/or FantasyPros / Tank01 token files) |
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
