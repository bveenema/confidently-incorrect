#!/usr/bin/env bash
# Seed the issue backlog for Confidently Incorrect.
# Requires: gh CLI authenticated, run from the repo root.
#
#   ./seed-issues.sh --labels     # create labels only
#   ./seed-issues.sh              # create labels then issues
#
# Issues are sized so one is roughly one /autopilot run. Dependencies
# are stated in the body rather than enforced — Hephaestus picks by
# priority, so create them in order and let the queue drain top-down.

set -euo pipefail

mklabel() { gh label create "$1" --color "$2" --description "$3" --force >/dev/null; }

echo "Creating labels…"
mklabel "milestone:draft"  "FF7F2A" "Must ship before 6 Sep draft"
mklabel "milestone:week1"  "D4537E" "Must ship before week 1 kickoff"
mklabel "milestone:season" "7F77DD" "In-season, no hard deadline"
mklabel "area:yahoo"       "378ADD" "Yahoo API client and auth"
mklabel "area:council"     "1D9E75" "Personas, orchestration, prompts"
mklabel "area:data"        "BA7517" "Projections, scoring, ledger"
mklabel "area:web"         "888780" "Log site and admin console"
mklabel "area:infra"       "5F5E5A" "Containers, timers, deploy, alerting"
mklabel "verification"     "EF9F27" "Resolves a row in followups.md"
mklabel "blocked"          "E24B4A" "Waiting on an external answer"

[[ "${1:-}" == "--labels" ]] && { echo "Labels only. Done."; exit 0; }

mkissue() {
  local title="$1"; shift
  local labels="$1"; shift
  local body="$1"; shift
  gh issue create --title "$title" --label "$labels" --body "$body" >/dev/null
  echo "  + $title"
}

echo "Creating draft-milestone issues…"

mkissue "Project scaffold and container dev environment" \
"milestone:draft,area:infra" \
'Python project skeleton, Podman dev container, Makefile with the targets `CLAUDE.md` declares.

## Acceptance criteria
- [ ] `make test`, `make lint`, `make fmt`, `make build` all run
- [ ] Dev container runs the app locally with a mounted `/srv/ci/` equivalent
- [ ] Runtime state directory is outside the git working tree
- [ ] `git clean -nxd` lists nothing under the state directory
- [ ] Resolves followups A-9'

mkissue "Yahoo OAuth: authorize once, persist token, refresh unattended" \
"milestone:draft,area:yahoo" \
'**Critical path. Day-2 gate — if this is not working, live draft advisory is cut.**

One-time browser authorization with `redirect_uri=oob`, token persisted to the state volume, refresh working without a human.

## Acceptance criteria
- [ ] Reads own team, league settings, and a roster
- [ ] Token survives a container restart
- [ ] Refresh succeeds unattended after expiry
- [ ] A 401 is surfaced as an error, never swallowed
- [ ] Token file is a podman secret or volume-mounted, never in the image
- [ ] Resolves followups A-1'

mkissue "Ingest league settings and the full scoring table" \
"milestone:draft,area:yahoo,area:data" \
'Pull league settings and the complete scoring table from the API at runtime. Nothing derived from them is hardcoded.

## Acceptance criteria
- [ ] Team count, roster slots, scoring values, deadlines, waiver rules all read live
- [ ] Cached per run and diffed against the previous run
- [ ] A change logs loudly (see architecture D-47)
- [ ] Works unchanged if the league grows from 8 to 12 teams'

mkissue "Scoring engine: stat line to league points" \
"milestone:draft,area:data" \
'Compute fantasy points from raw stat projections using the ingested league scoring table. Never consume a provider precomputed point total.

This league is heavily customized — 1 pt per completion, 15 yd/pt passing, 6 pt passing TD. Elite QBs score roughly 3x skill players.

## Acceptance criteria
- [ ] Correct points for QB, RB, WR, TE, K, DEF from a stat line
- [ ] Integer rounding (fractional points are off)
- [ ] Unit tests covering each scoring category including the kicker distance bands and DST tiers
- [ ] Handles the "Negative Points: No" interpretation once resolved (followups A-6)'

mkissue "FantasyPros client: stat-level projections" \
"milestone:draft,area:data" \
'## Acceptance criteria
- [ ] Returns stat-level projections, not point totals
- [ ] Weekly and rest-of-season
- [ ] Captures standard deviation (input to the variance knob, D-21)
- [ ] Captures injury and news fields
- [ ] Attribution string available for the public site footer
- [ ] Resolves followups A-2'

mkissue "Tank01 client: projections, injuries, betting odds" \
"milestone:draft,area:data" \
'Secondary projection source. Disagreement between sources is signal (architecture 3.1).

## Acceptance criteria
- [ ] Stat-level projections
- [ ] Implied team totals derived from betting lines
- [ ] Injury and player news
- [ ] Stays within the 1000 req/day Pro tier'

mkissue "Player pool: merge sources, tier, compute ADP delta" \
"milestone:draft,area:data" \
'Merge both projection sources under league scoring, rank, tier by position, and compute delta against published ADP.

The QB inflation should surface here as a large exploitable gap. If it does not, the scoring engine is wrong.

## Acceptance criteria
- [ ] Per-player: both source values plus the delta
- [ ] Positional tiers with identified tier breaks
- [ ] ADP vs. our value ranking, sorted by gap
- [ ] Sanity check: top QBs rank far above their ADP'

mkissue "Draft board: poll draft results, compute available pool" \
"milestone:draft,area:yahoo" \
'Poll the draft results endpoint during a live draft, maintain drafted/available state.

## Acceptance criteria
- [ ] Polls without hitting rate limits
- [ ] Correctly identifies our next pick number and the snake turn
- [ ] Manual pick entry as fallback if polling stalls
- [ ] Verified against a live mock draft (followups A-4)'

mkissue "Draft display: local page with tiers, roster, next pick" \
"milestone:draft,area:web" \
'Usable with no models involved — this alone is a working draft tool.

## Acceptance criteria
- [ ] Available players by tier, our roster so far, next pick number
- [ ] Updates as the board changes
- [ ] Readable at a glance under a 1-minute clock'

mkissue "Council orchestrator: OpenRouter, brief schema, validation" \
"milestone:draft,area:council" \
'Parallel specialist calls, structured brief validation, GM pass. Per architecture 6 and council-prompts.md.

## Acceptance criteria
- [ ] Specialists run in parallel against one packet
- [ ] Briefs validated against the schema; malformed briefs rejected, not retried blind
- [ ] Every player_key validated against the live pool
- [ ] A missing specialist does not block; a missing GM decision does
- [ ] Per-call model, tokens, and cost recorded'

mkissue "Draft council integration: ranked output, background recompute" \
"milestone:draft,area:council" \
'Belichuk, Brand, Taco into Maddox on the draft packet. Muskett sits the draft out.

**Output must be a ranked list of at least 5, never a single pick** — the snake turn produces back-to-back picks under a 1-minute clock (D-49).

## Acceptance criteria
- [ ] Recomputes in the background after every pick by anyone
- [ ] Ranked list of 5+ always available when our turn arrives
- [ ] Falls through to tier-based best-available on any model failure
- [ ] Lasso writes an opening note at draft start and a closing note at the end'

mkissue "Pre-rank sheet export" \
"milestone:draft,area:data" \
'Top ~200 by our scoring, in a form that can be entered into Yahoo pre-rank by hand. No API exists for this.

## Acceptance criteria
- [ ] Ordered list, printable or copy-pasteable
- [ ] Ordering reflects league scoring, not published ADP
- [ ] Resolves followups A-7 once entered'

mkissue "Dry-run mode" \
"milestone:draft,area:infra" \
'Full pipeline, no writes to Yahoo. A first-class feature, not a debug flag — `/ship` gates on it for submission-path changes.

## Acceptance criteria
- [ ] `make dry-run` exercises lineup, waiver, and trade paths
- [ ] Prints what would have been submitted
- [ ] Exits non-zero on any failure'

echo "Creating week-1 issues…"

mkissue "kb.db schema: ledger, attribution, deploys, config changes" \
"milestone:week1,area:data" \
'Per architecture 7.1. Includes `season_id` from the first write (D-74).

Tables: seasons, runs, briefs, considered_options, decisions, outcomes, attributions, executions, deploys, config_changes.

## Acceptance criteria
- [ ] `season_id` on runs, deploys, config_changes
- [ ] WAL mode; parallel specialist writes do not conflict
- [ ] Failed runs are rows with a failure mode, never omitted
- [ ] Migration script; runtime DB lives on the state volume'

mkissue "Guardrails module" \
"milestone:week1,area:council" \
'Deterministic validation between the GM decision and the Yahoo call. Per architecture 8.

## Acceptance criteria
- [ ] No empty starting slots, no bye or Out players started
- [ ] Waiver claim respects the priority floor
- [ ] Trade validity checks only — **no quality floor** (D-26)
- [ ] Blocked actions produce an in-character IT/HR/Legal note (D-27)
- [ ] Every rejection logged'

mkissue "Lineup pass: pre-check, council, guardrails, submit" \
"milestone:week1,area:yahoo,area:council" \
'The operational floor. This ships before anything else in the season engine.

Five-plus passes per week, one per lock window, each after the relevant inactive report (D-56, D-57).

## Acceptance criteria
- [ ] Deterministic pre-check exits without a model call when no slot is actionable
- [ ] `considered_options` snapshot written before execution (D-24)
- [ ] Retries bounded by the lock window, not a fixed count
- [ ] On failure the existing lineup stands and an alert fires — no deterministic substitution (D-60)
- [ ] Late passes accept live matchup state and shift variance (D-65)'

mkissue "Pseudonymization at ingest" \
"milestone:week1,area:yahoo" \
'Manager and team names mapped to stable pseudonyms in the Yahoo client, before storage or any prompt.

## Acceptance criteria
- [ ] Mapping table outside kb.db and notes/
- [ ] No real name reaches the ledger, notes, prompts, or logs
- [ ] Team names mapped too, not just managers
- [ ] Build-time check fails the site build if a mapped name appears in output'

mkissue "Alerting: push notifications with severity tiers" \
"milestone:week1,area:infra" \
'Pushover or ntfy. Not Slack, not email (D-59).

## Acceptance criteria
- [ ] P1 repeats until acknowledged; P2 single push; P3 weekly digest
- [ ] Alert states what failed, current roster state, and what can be done
- [ ] Auth failure is P1 immediately, not after retries
- [ ] Verified end to end on a locked phone (followups B-7)'

mkissue "Dead-man switch integration" \
"milestone:week1,area:infra" \
'External service. Ping on confirmed successful submission, never on process start (D-62).

## Acceptance criteria
- [ ] Each scheduled run registers its own check with an expected window
- [ ] A run that submits nothing does not ping
- [ ] Missing ping alerts as P1
- [ ] Verified by disabling a timer deliberately (followups B-8)'

mkissue "systemd timers and Quadlet units" \
"milestone:week1,area:infra" \
'All scheduled runs per architecture 5. `TZ=America/New_York`.

## Acceptance criteria
- [ ] Type=oneshot, no overlapping runs
- [ ] Units survive a reboot
- [ ] journald logging usable for debugging a missed run
- [ ] Timer list matches the schedule table exactly'

mkissue "deploy.sh with freeze window, tagging, and rollback" \
"milestone:week1,area:infra" \
'Per architecture 9.5.

## Acceptance criteria
- [ ] Refuses inside the freeze window without `--emergency`
- [ ] Builds tagged by short SHA, keeps the last five
- [ ] `--rollback <sha>` retags without rebuilding and works offline
- [ ] Writes a `deploys` row
- [ ] Runs a dry-run pass and fails loudly if it does not complete
- [ ] Resolves followups A-10'

echo "Creating season issues…"

mkissue "Waiver pass: rolling priority, weekly and daily" \
"milestone:season,area:yahoo,area:council" \
'**No FAAB in this league** (D-50). The resource is waiver priority position.

Weekly claims submitted Monday evening before Tuesday processing, plus a daily pass for off-cycle clears (D-54, D-55).

## Acceptance criteria
- [ ] Deterministic pre-check skips the model call when nothing is clearing
- [ ] Priority cost modelled explicitly
- [ ] Verified against actual Yahoo processing time (followups B-2)'

mkissue "IR slot automation" \
"milestone:season,area:yahoo" \
'Move eligible rostered players to IR as part of the waiver pass; activate when appropriate (D-66).

## Acceptance criteria
- [ ] Never attempts to add from waivers/FA directly to IR (league setting forbids it)
- [ ] Activation that forces a drop goes through normal waiver-pass reasoning'

mkissue "Trade poll and incoming offer evaluation" \
"milestone:season,area:yahoo,area:council" \
'Six-hourly poll. Muskett, Brand, Belichuk into Maddox.

## Acceptance criteria
- [ ] Reads the counterparty trade note if exposed (followups B-4)
- [ ] Real assessment, no rubber-stamping either way
- [ ] Tracks the 2-day league-vote review window; a trade is not final on accept
- [ ] Veto probability weighted by team count (D-53)'

mkissue "Trade initiation pipeline" \
"milestone:season,area:council" \
'Needs-first, four stages, per architecture 7.3. Stage 0 is deterministic with no model involved.

## Acceptance criteria
- [ ] Stage 0 generates candidate shapes from roster complementarity, no LLM
- [ ] Specialists brief on needs, not on packages
- [ ] Muskett alone constructs packages (D-37)
- [ ] Ranked by improvement weighted by acceptance likelihood
- [ ] **Zero trades is a valid, logged outcome** (D-33)'

mkissue "Trade notes, expiry, withdrawal, and anti-spam" \
"milestone:season,area:yahoo" \
'## Acceptance criteria
- [ ] Notes signed exactly `"E" Muskett [xAI]`
- [ ] Self-imposed expiry per offer, minimum 24h, auto-withdraw on expiry
- [ ] Cooldowns graduated by rejection type (D-28)
- [ ] Deterministic similarity guard comparing player sets (D-29)
- [ ] Nudge at most once per offer, responsive managers only (D-35)
- [ ] Verify programmatic cancel works (followups B-5)'

mkissue "Trade partner modeling" \
"milestone:season,area:data" \
'Structured counts in kb.db, qualitative observations in `notes/managers/`.

## Acceptance criteria
- [ ] Response rate, timing, accept/reject/counter ratio, positional holes, bye gaps
- [ ] Personas write observations with wikilinks and YAML front matter including season
- [ ] **`notes/managers/` excluded from both site builds unconditionally** (D-31)'

mkissue "Attribution scoring job" \
"milestone:season,area:data" \
'Computes all three measures for every persona including overruled briefs. Per architecture 7.2.

## Acceptance criteria
- [ ] Counterfactual points, directional accuracy, Brier contribution
- [ ] Every persona graded, `adopted` flag set (D-23)
- [ ] Sample size available alongside every rate
- [ ] Weeks with manual intervention flagged and excluded'

mkissue "Log site generator: private and public builds" \
"milestone:season,area:web" \
'Static generation from kb.db, pushed to Cloudflare Pages.

## Acceptance criteria
- [ ] Private build gated by Access on a league allowlist
- [ ] Public build renders only runs with `publish_approved`
- [ ] Trade notes included in the public build (D-19)
- [ ] FantasyPros attribution in the footer (followups C-3)
- [ ] Build fails if any mapped real name appears in output'

mkissue "Admin console: FastAPI behind Cloudflare Tunnel" \
"milestone:season,area:web,area:infra" \
'Per architecture 9.3.

## Acceptance criteria
- [ ] FastAPI binds 127.0.0.1 only; cloudflared container holds the tunnel
- [ ] Access policy with a single-email allowlist
- [ ] Season summary, council accuracy with sample sizes, knobs, trade monitor, health
- [ ] Every knob change writes a `config_changes` row (D-68)
- [ ] Stats and trade monitor also render statically into the private site'

mkissue "notes/ narrative layer and Obsidian conventions" \
"milestone:season,area:data" \
'Git-backed markdown vault, read wholesale into every packet.

## Acceptance criteria
- [ ] Personas append only through a structured tool call that timestamps and attributes
- [ ] YAML front matter on every model-written note including season
- [ ] Wikilinks to players and manager pseudonyms
- [ ] Bare git repo on the VPS as the sync remote'

echo
echo "Done. Review with: gh issue list --label milestone:draft"
