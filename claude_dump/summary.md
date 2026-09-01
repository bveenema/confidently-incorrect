# Confidently Incorrect — project summary

A record of what was decided, in what order, and what is still open.
Written 27 August 2026, ten days before the draft.

---

## What this is

A Yahoo fantasy football team managed entirely by a council of LLM
personas drawn from five vendors, with its decision reasoning published
to a gated page and every persona's calls graded against counterfactual
outcomes.

Ben knows nothing about football. That is the premise, not a problem to
solve.

**Team: Confidently Incorrect.** 8-team work league, expected to grow to
10-12. Draft Sunday 6 September 2026, 20:00 EDT.

---

## The documents

| File | What it holds |
|---|---|
| `architecture.md` | Design decisions and the numbered decision log (D-1 … D-74) |
| `implementation.md` | Build order, ten-day critical path, league facts |
| `followups.md` | Open verifications with deadlines and consequences |
| `council-prompts.md` | Persona system prompts and the brief schema |
| `.ai/rules.md` | Binding rules for AI agents doing implementation |
| `.ai/README.md` | Index for the `.ai` convention folder |
| `CLAUDE.md` | Project config Hephaestus reads at runtime |
| `seed-issues.sh` | 32-issue backlog seeded into GitHub |
| `admin-console-mockup.html` | Admin console design mockup |
| `confidently-incorrect-*.png/.svg` | Team logo, five files |

---

## How the conversation went

**Feasibility first.** Yahoo's Fantasy API can read everything and write
lineups, waivers, and trades — but there is no draft-pick endpoint and no
message board API. That shaped everything downstream: the draft is
advisory, and trade notes are the only channel for talking to other
managers.

**Then strategy, then the council.** What began as "should the bot be
aggressive or passive" turned into a five-persona council on five
vendors, with a sixth persona outside the decision path for colour.
Personas are lightly distorted real and fictional names, defined by
trait specifications rather than impersonation.

**Then the hard part: measurement.** Most of the design weight ended up
on outcome attribution — how to tell whether a decision was good,
separately from whether the week went well. That is what turns the
project from a gimmick into an experiment, and it drove the dual
knowledge base, the `considered_options` snapshot, and the decision to
grade overruled briefs.

**Then the league settings arrived and invalidated several things.** No
FAAB. All eight teams make the playoffs. QB scoring inflated to roughly
3× normal. Trades subject to league vote. Each of those forced a
correction, which is why the follow-ups register exists.

---

## The council

| Role | Handle | Model | In decision path |
|---|---|---|---|
| GM | "Big John" Maddox | Gemini | Yes — final call, breaks ties |
| Coach | Coach Belichuk | Anthropic | Yes — lineup |
| Analyst | Peter Brand | OpenAI | Yes — projections, EV |
| Negotiator | "E" Muskett | xAI | Yes — trades only |
| Scout | "Taco" Macarthy | DeepSeek / Qwen | Yes — waivers, sleepers |
| Asst. Coach | Coach Lasso | cheapest | No — pregame and postgame colour |

Specialists emit structured briefs in parallel against one packet; the
GM sees them all and decides. Personality is quarantined to a single
`voice_line` field so the GM always has parseable reasoning. Confidence
scores are deliberately miscalibrated per persona and the GM knows it.

Anthropic went to Belichuk rather than the GM because terseness is the
hardest constraint to hold, and a coach who gradually becomes articulate
is the least funny possible failure.

---

## Decisions that shaped everything else

**Success criteria, ranked:** entertainment > decision quality > win
rate > experiment integrity. With the explicit rider that entertainment
never licenses deliberately bad play — the council always tries to win,
and the comedy comes from the reasoning being visible.

**Full autonomy from week 1.** No propose-mode warm-up, no human in the
loop on trades. Being out-negotiated by a coworker is a protected
feature; there are validity guardrails but no quality floor.

**No deterministic lineup fallback.** If the council cannot decide before
kickoff, the existing lineup stands and Ben gets an alert. A failure to
decide is a council failure with real consequences, including the
possibility of starting a player on bye.

**Attribution captured at decision time.** Every option any persona
evaluated is snapshotted before execution, because the counterfactual is
unrecoverable a week later. All three measures recorded; every persona
graded, including on briefs the GM overruled.

**Pseudonymization at ingest.** Real names never enter the store or any
prompt. A model that never saw a name cannot leak one.

**Partner models stay private indefinitely.** The one artifact where
being factually correct is also unkind.

---

## Architecture in one paragraph

Python in Podman on a cheap Vultr VPS, driven by systemd timers rather
than cron. Outbound only — the log site is statically generated and
pushed to Cloudflare Pages behind Access; the admin console is FastAPI
bound to localhost behind a Cloudflare Tunnel. Dual knowledge base:
SQLite for the decision ledger where the queries are aggregations,
markdown in git for the narrative layer, opened in Obsidian on the
workstation. No vector store — a season fits in context. Projections
from FantasyPros and Tank01, recomputed from stat lines because no
published source uses this league's scoring.

---

## League facts that changed the design

- **No FAAB.** Continual rolling waiver priority. The resource is
  position, not a budget.
- **All 8 teams make the playoffs** — at the current size. Compute
  playoff odds properly anyway; the league is growing.
- **QB scoring inflated ~3×.** 1 pt per completion, 15 yd/pt passing,
  6 pt passing TDs. Draft QBs early regardless of ADP.
- **Trades go to a league vote**, 2-day review. Not final on acceptance.
- **1-minute pick clock** and a snake turn, so the council must always
  output a ranked list rather than a single pick.
- **Players lock individually at kickoff**, so there are five-plus lineup
  passes a week, each timed after the relevant inactive report.

---

## Where it stands

**All eleven open questions resolved except O-11** (season-end and
archival), deliberately deferred to December with one hedge taken now:
`season_id` stamped on records from the first write.

**Implementation runs through Hephaestus** — issue-queue-driven workflow
with `/autopilot` pulling from GitHub issues. 32 issues seeded across
three milestones. Local dev in containers, PRs with squash merge,
deploys by SSH from Cursor running `deploy.sh`.

**The ten-day critical path:**

1. Days 1-2 — OAuth end to end. The gate. If it is not working, live
   draft advisory is cut and the cheat sheet ships alone.
2. Days 2-5 — settings ingestion, scoring engine, projections, tiers
3. Days 5-6 — draft loop skeleton, usable with no models involved
4. Day 6 — mock draft rehearsal, the only way to learn whether the draft
   results endpoint is fresh enough
5. Days 7-8 — council integration
6. Day 9 — pre-rank sheet entered by hand
7. Day 10 — dry run and buffer

**Before the draft, four things need answers from outside the code:**
whether FantasyPros returns stat-level projections on the purchased
tier, what "Negative Points: No" actually means, the final team count,
and telling the league what is about to happen.
