# Confidently Incorrect — System Architecture

**Team:** Confidently Incorrect (Yahoo Fantasy Football, 12-team work league)
**Premise:** roster managed entirely by a council of LLM personas, openly
disclosed to the league. Decision reasoning published to a gated page.
**Status:** design. Nothing built yet.

Companion document: `council-prompts.md` (persona prompts + brief schema).

---

## 1. Goals and non-goals

**Goals**
- Automate lineups, waivers, and trade responses with no human input
  during the season
- Produce a readable, entertaining decision log for the league
- Compete honestly — the bot should try to win
- Learn how to build an AI-in-the-loop app rather than an AI-built one

**Non-goals**
- Real-time draft automation (not possible via API — see §3)
- Beating a dedicated human manager on pure performance
- Any capability that outlives this season

**Success criteria — RESOLVES O-1**

Ranked. The top one breaks ties when they conflict.

1. **Entertainment value for the league**
2. **Decision quality** (counterfactual points)
3. **Win rate / final standing**
4. **Experiment integrity** (does the council add value)

**Critical reading of #1.** Entertainment comes from the reasoning being
visible and the personas being distinct — not from the bot playing
badly. Deliberate incompetence is both a violation of #2 and, in
practice, not funny past about week 3. **The council always tries to
win.** Nothing in this system may instruct a persona to make a decision
it believes is worse in order to be amusing.

What the ranking actually licenses, given that:

- Variance defaults lean higher than pure EV-maximization would set
  them. A boom-or-bust week produces a story; a quietly correct one
  produces a spreadsheet row.
- Personas keep their distinct voices and distinct priors even where
  convergence would be more accurate. Do not tune the specialists
  toward the Analyst over the season.
- Taco stays in the decision path despite low expected accuracy. His
  inflated confidence is discounted by the GM, not removed.
- The GM is not a rubber stamp for Brand's numbers. Disagreement that
  actually resolves somewhere is the content.

**Decision quality above win rate** is deliberate and the more
interesting of the two. A well-reasoned loss is a better artifact than a
lucky win, and the attribution data (§7.2) is what makes that
distinction visible rather than rhetorical.

**Experiment integrity ranked last** costs nothing — the data collection
is the same either way. It simply loses ties.

**Operational floor, independent of the ranking: never miss a lineup
lock.** This trades off against nothing, serves every criterion, and is
the single failure that would be genuinely embarrassing in a work
league. Treat any missed lock as a P1 defect.

**Autopilot at season start: full autonomy from week 1.** No propose-
mode warm-up. Early mistakes are content, and a human in the loop for
the first two weeks would compromise the cleanest stretch of
attribution data of the season.

---

## 2. Constraints

| Constraint | Source | Impact |
|---|---|---|
| One team per OAuth token | Yahoo | No multi-team AI competition |
| No draft-pick endpoint | Yahoo | Draft is advisory only |
| No message board / chat API | Yahoo | Trade notes are the only text channel |
| Trade notes reach real coworkers | Social | Content constraint on Negotiator |
| Players lock individually at kickoff | NFL | Multiple lineup runs per week |
| Access token expires hourly | Yahoo | Refresh token must persist across restarts |
| Max 6 pending trade offers | Yahoo | Limits Negotiator aggression |
| Trades reviewed by league vote, 2 days | League | Trade not final on accept; can be reversed |
| 8 playoff spots, 8-12 teams (fluid) | League | Race exists only above 8 teams — derive, don't hardcode |
| No FAAB — rolling waiver priority | League | Priority position is the resource, not a budget |
| Scoring heavily customized (QB-inflated) | League | Published projections unusable; recompute from stat lines |
| Fractional points off | League | Integer scoring; round projections |
| 10-day trade response window | Yahoo | Async negotiation, ~1 exchange/day |

---

## 3. What Yahoo's API can and cannot do

**Can (read):** rosters, players, projections, free agents, matchups,
standings, transactions, draft results, league settings and scoring.

**Can (write):** lineup changes, add/drop, waiver claims (rolling priority — this league has no FAAB),
trade proposals with a `trade_note`, accept/reject/counter.

**Cannot:** submit a draft pick, set pre-draft rankings, post to the
league message board, DM another manager outside a trade note.

**Draft approach — RESOLVES O-2**

**Draft: Sunday 6 September, 20:00 EDT. Yahoo Live Standard Draft, 15
rounds, 1-minute pick clock. Room opens 30 minutes prior.**

**Team count is fluid** — 8 confirmed, at least 2 more expected, cap 12.
The draft tool reads team count and pick order at draft start, not at
build time.

Approach: **live advisory with a pre-rank cheat sheet as fallback.**

#### The latency problem dissolves

The naive design computes a recommendation when the pick clock starts,
which is tight — the clock is 1 minute. Unnecessary in the general case:
there are (teams − 1) other picks between each of ours — roughly 7
minutes of wall clock at 8 teams, 11 at 12. Larger leagues make this
easier, never harder.

**Exception: the turn.** Snake order means picks 8 and 9 (and 16/17,
etc.) come back to back with no gap. The council must therefore always
output a **ranked list of at least 5 candidates, never a single pick**,
so the second selection at the turn is already answered.

**The council recomputes in the background after every pick by anyone.**
When our turn arrives the recommendation is already rendered. The pick
clock never gates a model call. Worst case the board moved on the pick
immediately before ours, and a partial refresh still beats nothing.

#### Scope — this is a separate, smaller build

The draft assistant is **not** the season engine. It does not need
SQLite, Obsidian, the log site, guardrails, trade logic, or the VPS. It
can run on the workstation. Build it standalone and throw most of it
away afterward.

Critical path, in order:

1. **OAuth working end to end.** This is the real risk and the thing
   most likely to consume days. Do it first, not last.
2. **Player pool + FantasyPros projections and ADP**, tiered by
   position.
3. **Live loop:** poll the draft results endpoint → compute who is
   available → run council → render.
4. **Display:** a local page or terminal view. No styling budget.
5. **Pre-rank cheat sheet** generated and entered into Yahoo. Manual
   data entry, no API for it — do this on day 9, it is labour not build
   time.

#### Council composition for the draft

Muskett is irrelevant here — no trades during a live draft. Run
Belichuk, Brand and Taco as specialists into Maddox. Lasso writes an
opening note when the draft starts and a closing one when it ends.

Draft-specific packet contents: roster slots filled so far, positional
scarcity remaining, tier breaks, ADP versus current pick number, bye
week collisions on the existing roster, and the draft strategy setting
(Zero RB / Robust RB / best available) from `strategy.json`.

#### Rehearsal

Join a Yahoo mock draft before the 6th and run the polling loop against
it live. This is the only way to find out whether the draft results
endpoint updates fast enough and what its shape looks like mid-draft,
and it costs an hour. Do it by day 6 so there is time to react.

#### Fallbacks, in order

- Model call fails or times out → fall through to tier-based
  best-available from the precomputed list, no model involved
- Polling stalls → manual entry of picks made, keyboard only
- Connection drops entirely → Yahoo autopick follows the pre-rank sheet
- No pre-rank sheet entered → Yahoo falls back to its own default
  rankings, which is survivable but strictly worse

The pre-rank sheet is the outermost net. It is worth entering even if
the live tool works perfectly.

**Auth:** OAuth 2.0, app registered with Fantasy Sports **Read/Write**
permission. Initial authorization done once on a workstation with a
browser; resulting token file mounted into the container. Refresh
happens unattended thereafter.

---

## 3.1 Projection data sources — RESOLVES O-6

Yahoo's own projections come through the API but are mediocre, and every
persona's reasoning quality is bounded by this input. Two paid sources,
no scraper.

**FantasyPros — primary.** Consensus rankings and projections aggregated
from 130+ experts, with tiers and the spread of opinion (best, worst,
standard deviation), weekly and rest-of-season projections with full
stat lines, plus injuries and news. Production API access is bundled
with a FantasyPros HOF subscription, from $8.99/mo on annual billing —
roughly $45 for a five-month season if monthly billing is available,
~$108 if annual only.

- The free tier is explicitly non-production. The subscription is
  required.
- License is personal and non-commercial. Fine for this project.
- **Attribution is mandatory.** FantasyPros must be credited when
  publishing work based on API data. Applies directly to the public log
  page (§9.2); a footer credit line satisfies it.

**Tank01 (RapidAPI) — secondary.** Pro tier $10/mo for 1,000 req/day.
Fantasy projections updated hourly, plus injuries, player news, betting
odds and player props. ~$50 for the season.

**Combined: ~$95-100 per season.** Within budget.

**Why two sources.** Disagreement between projection sources is itself
signal, and it gives the Analyst something to reason about beyond
restating a single number. "Consensus has him at 12.4, the live model
has him at 9.1, and the gap is injury-related" is a materially better
brief than either source alone produces. Record both values and the
delta in the packet.

**Two fields worth special handling:**

- **Standard deviation** (FantasyPros) is the direct input to the
  variance knob. High-spread players are the boom-or-bust starts when
  chasing upside and precisely what to avoid when protecting a lead.
  Wire this to `strategy.json` variance explicitly rather than leaving
  the model to infer the connection.
- **Implied team totals** from betting lines (Tank01) are among the
  better weekly fantasy signals, and nothing else in the stack carries
  them.

**Rejected:** FantasyNerds — moved to a single annual plan at $499/year.
Scraping — excluded by constraint. nflverse is free but historical only;
useful later for backtesting, not for weekly decisions.

---

## 4. Infrastructure

```
Vultr VPS (shared CPU, ~$5-6/mo, TZ=America/New_York)
│
├── systemd timers (Quadlet .container + .timer units)
│   └── engine container (ephemeral, Type=oneshot)
│         ├── Yahoo API client
│         ├── packet builder
│         ├── council orchestrator → OpenRouter
│         ├── deterministic guardrails
│         └── static site generator
│
├── volume: /srv/ci/
│   ├── kb.db            SQLite (WAL) — decision ledger
│   ├── notes/           markdown, git repo — narrative layer
│   ├── strategy.json    strategy config, read fresh each run
│   └── tokens/          Yahoo OAuth token (podman secret)
│
└── outbound only — no inbound ports
      └── pushes built static site → Cloudflare Pages
            └── Cloudflare Access (work email domain policy)
```

**Why a VPS at all:** decoupling Sunday-morning uptime from home power
and ISP. The static IP is not actually required by anything — Yahoo's
redirect needs a stable hostname, not a fixed address.

**Why systemd timers over cron:** journald logging, `Type=oneshot`
semantics, no overlapping runs, failure notification. Cron gives a
silent Sunday miss debuggable only through shell redirects.

**Why Pages over an always-on web container:** no inbound ports, no TLS
management, Access gating for free, and the same pattern already in use
for nhi-docs.

**Cost note:** Vultr auto-backups add 20%; stopped instances still
bill until destroyed.

---

## 5. Schedule

| When (ET) | Run | Personas |
|---|---|---|
| Thu ~17:00 | TNF slots only | Belichuk, Brand, Taco → Maddox |
| Sun ~11:45 | Main lineup — **after 1pm inactives post** | Belichuk, Brand, Taco → Maddox → Lasso [PREGAME] |
| Sun ~15:30 | Late-afternoon slate slots | Belichuk, Brand, Taco → Maddox |
| Sun ~19:45 | SNF slots | Belichuk, Brand, Taco → Maddox |
| Mon ~19:45 | MNF slots | Belichuk, Brand, Taco → Maddox |
| Fri/Sat ~as scheduled | International or late-season Saturday games | same panel |
| Mon ~20:00 | Weekly waiver claims — **submitted before Tuesday processing** | Taco, Brand → Maddox |
| Daily ~20:00 | Rolling waiver pass — anything clearing in next 24h | Taco, Brand → Maddox (skipped if nothing clearing) |
| Tue ~09:00 | Results + log close, waiver outcomes | Lasso [POSTGAME] |
| Every 6h | Trade poll | Muskett, Brand, Belichuk → Maddox (only if pending) |

**The lineup is not one weekly decision.** Players lock individually at
their own kickoff, so each week is a sequence of constrained decisions
with different deadlines. Each pass decides only the slots still open,
against a shrinking pool of unlocked players — an early lock permanently
removes options from every later pass.

**Inactives drive the timing.** The NFL publishes inactives 90 minutes
before kickoff, so 11:30 ET for the 1pm slate. A run at 11:00 sets the
lineup before the single most decision-relevant piece of information
arrives. Every lineup pass is scheduled to land *after* the inactive
report for the games it covers and with enough margin to retry.

**Most passes are no-ops.** A deterministic pre-check establishes
whether any slot is open and any eligible unlocked player exists to fill
it. If not, the pass exits without a model call. Same pattern as the
daily waiver pass.

**Same panel for every lineup pass.** Belichuk, Brand and Taco into
Maddox, regardless of which slate it covers. Decision type determines
the panel, not the day of the week.

**Waiver timing is submit-before-process.** Yahoo processes the weekly
batch Tuesday at game time; a run scheduled *at* processing time misses
the window entirely. The weekly run goes Monday evening with room for a
retry.

**Continual rolling list means waivers do not only clear on Tuesday.**
Each player clears individually two days after hitting waivers, so a
player dropped Thursday clears Saturday. A weekly-only run misses every
off-cycle clear — which is precisely where uncontested value sits, since
fewer managers are paying attention. Hence the daily pass.

The daily pass is cheap: deterministic code checks whether anything is
clearing in the next 24 hours and exits without a model call if not.
Only a genuine candidate triggers the council.

### Lineup pass specifics — RESOLVES O-3

**Thursday option value.** Starting a TNF player locks that slot for the
whole week, forfeiting its use on anyone playing later, and the call is
made with the least information available all week. There is **no
deterministic margin rule** — the judgement is Belichuk's.

But he must be told about the asymmetry, because it is not visible in
the projections alone: a Thursday player projected at 11 and a Sunday
alternative projected at 10 are not equivalent, since the Sunday option
retains upside from news that has not broken yet. The Thursday packet
states this explicitly and lists the best available alternative at that
slot for each later slate.

**Score-aware late passes.** Sunday-night and Monday passes receive
**live matchup state** — current score, opponent's remaining players,
our remaining players — and shift variance accordingly:

- Trailing badly with few players left → maximise ceiling, not
  projection. Start the boom-or-bust option
- Winning comfortably → minimise variance, protect the lead
- Mathematically decided either way → say so and do nothing

This is the variance knob applied live rather than set weekly. It
overrides the `strategy.json` variance setting for that pass only, and
the override is recorded so attribution can see why a high-variance
start was chosen.

Good log material too: "we need 31 points from one player, so we are
starting the boom-or-bust option" is a real decision with visible
reasoning and a visible outcome.

**IR slots.** Two available. Moving a genuinely injured rostered player
to IR frees an active spot for a waiver pickup, and it is a mid-week
decision humans routinely forget.

- **Automated as part of the waiver pass.** The council moves eligible
  players to IR and activates them off IR when appropriate.
- Note the league setting: injured players cannot be added directly
  from waivers or free agency into an IR slot. This applies only to
  players already rostered.
- Activating off IR while the roster is full forces a corresponding
  drop — that is a real roster decision and goes through the normal
  waiver-pass reasoning, not an automatic rule.

---

## 6. The council

| Role | Handle | Model | In decision path |
|---|---|---|---|
| GM | "Big John" Maddox | Gemini | Yes — final call, breaks ties |
| Coach | Coach Belichuk | Anthropic | Yes — lineup |
| Analyst | Peter Brand | OpenAI | Yes — projections, EV |
| Negotiator | "E" Muskett | xAI | Yes — trades only |
| Scout | "Taco" Macarthy | DeepSeek / Qwen | Yes — waivers, sleepers |
| Asst. Coach | Coach Lasso | cheapest | No — pregame/postgame color |

**Protocol:** specialists emit structured briefs in parallel against an
identical packet. The GM sees all briefs at once and returns a decision.
One rebuttal round is allowed when two specialists directly conflict on
the same player; no further rounds.

**Personality is quarantined.** Every persona writes literal `reasoning`
for the GM and performs only in `voice_line`. Confidence scores are
deliberately miscalibrated per persona and the GM prompt accounts for it.

**Vendor routing** via OpenRouter — one key, one schema. LiteLLM as a
local proxy is the alternative if key custody matters more than
simplicity.

**Cost estimate:** ~6-8 calls per decision, ~50 decisions per season,
25k in / 2k out per call. Low tens of dollars for the season. Cost is
not a design constraint here.

---

## 7. Knowledge base (dual store)

Two stores because there are two access patterns.

**`kb.db` — SQLite, WAL mode. Structured decision ledger.**

Holds every brief, every GM verdict, every outcome. Queried by
aggregation, not search: persona hit rates by confidence band, override
frequency, calibration drift. Schema enforcement matters because five
different vendors' models write into it — SQLite rejects a malformed
insert, a markdown file accepts anything. WAL handles the parallel
specialist writes.

Tables (draft):

- `seasons` — season_id (e.g. `2026`), league_key, team_key, start date,
  end date, final record, final placing
- `runs` — run id, **season_id**, timestamp, decision_type, packet hash
- `briefs` — run id, persona, recommendations JSON, confidence,
  reasoning, dissent, voice_line, model used, tokens, cost
- `considered_options` — run id, persona, player_key, contemplated
  action, projection at that moment (both sources plus delta), std-dev,
  injury status, whether chosen
- `decisions` — run id, final actions, adopted_from, overruled,
  override_reason, unanimous_override, rationale
- `outcomes` — run id, what actually happened, points gained/lost vs.
  the counterfactual where available
- `attributions` — run id, persona, counterfactual points, directional
  accuracy, Brier contribution, adopted flag
- `executions` — what was actually sent to Yahoo, response, errors,
  pending-review state for trades
- `deploys` — **season_id**, timestamp, commit SHA, description, whether
  decision logic was touched
- `config_changes` — **season_id**, timestamp, knob, old value, new
  value

**Season identifier.** `season_id` is stamped on `runs`, `deploys` and
`config_changes` from the first write. Child tables inherit it through
their run id, so it does not need repeating on every row.

This is cheap now and expensive later. Whether next season inherits
partner models and league lore is deferred (O-11), but that decision is
only available if the data is separable when it arrives. Retrofitting a
season column across 500 briefs and their attributions in December is a
migration nobody wants to write.

Also stamp `notes/` front matter with the season, for the same reason —
a manager observation from 2026 should be distinguishable from a 2027
one even though the file path is the same.

**`notes/` — markdown, git repo. Narrative layer.**

League lore, persona backstory, standing observations about specific
managers, scoring quirks, running jokes. Few files, read wholesale into
every packet, occasionally hand-edited. Git gives version history and
week-to-week diffs for free; the folder opens in Obsidian on the desktop.

**No index, no embeddings, no vector store.** A full season is roughly
500 briefs and a few thousand words of notes. It fits in context
uncompressed. There is nothing to retrieve against.

**Write discipline:** models may append observations to `notes/` only
through a structured tool call that timestamps the entry and attributes
it to a persona. Prevents the failure mode where a model entrenches an
early bad read and then cites its own note as evidence all season. Prior
predictions are fed back with outcomes attached so personas see their
own hit rate.

### 7.1 Obsidian layer

Obsidian is a desktop application, not a service. It does **not** run on
the VPS. It runs on Ben's workstation and opens the `notes/` folder as a
vault — the folder already is a vault, since Obsidian is a viewer over
plain markdown rather than a storage format.

Sync: the VPS holds a bare git repo; the workstation clones it and the
Obsidian Git plugin auto-commits and pulls on an interval. Syncthing is
the alternative if git friction gets annoying, and is the better option
if mobile access matters — Obsidian's iOS git support is poor.

This layer is explicitly a **learning objective**, not a requirement.
The system functions identically without it. Kept because the question
it answers — what happens when an agent rather than a human builds the
link graph — is worth an actual season of data.

Conventions that make it worth doing:

- **Personas write wikilinks.** Observations reference `[[Player Name]]`
  and `[[Manager Pseudonym]]`. The graph then builds itself with no
  curation. This is the part actually under study.
- **YAML frontmatter on every model-written note:** date, persona,
  entity type, week. Without it, Dataview queries are impossible later,
  and this is the step people skip and regret.
- **Try a Map of Content for league lore** alongside the emergent graph,
  and see which one actually gets used by week 10.

Two limits:

- Dataview queries must never be load-bearing. They render only inside
  Obsidian; nothing on the VPS can depend on them.
- The decision ledger does not migrate to markdown because it would look
  better in the graph. Aggregation queries are the entire reason SQLite
  is there.

---

### 7.2 Outcome attribution — RESOLVES O-8

**All three measures are recorded. Every persona is graded, including
on briefs that were overruled.**

#### What this is and why it exists

Outcome attribution connects a specific decision to a specific result,
so decision *quality* can be judged separately from how the week went.

The team's score alone says very little. A 130-point win can sit on top
of five bad calls, if the players who were benched would have scored
150. An 85-point loss can contain five correct calls against a roster
that was simply thin that week. Outcome is decision quality plus luck;
attribution separates them.

**Worked example.** Belichuk benches Player A (projected 12.4) and
starts Player B (projected 11.8) on a matchup read. Confidence 0.6.
Actual result: B scores 6, A scores 19.

- Counterfactual points: 6 − 19 = **−13**. The decision cost 13 points.
- Directional accuracy: **false**. The pick did not beat its
  alternative.
- Calibration: wrong at 0.6 is a modest penalty. Wrong at 0.95 would be
  a large one.

One instance of this is noise — football is enormously random and a
single week is uninformative. Across ~40 instances, patterns appear.
"Belichuk is right 58% of the time but his losses are larger than his
wins" means he is correctly calling coin flips and wrong on the
decisions that carry weight. That is actionable in a way a win-loss
record never is.

#### What it will be used for, in order of value

1. **Content.** "Belichuk has cost this team 31 points on start/sit
   calls he was 80% confident about" is a better log entry — and a
   better public post — than a record. The premise of this project is
   publishing reasoning; attribution is what makes that reasoning
   checkable rather than decorative.
2. **The actual research question.** Five vendors in defined roles is a
   gimmick without measurement. Attribution is what turns it into an
   experiment: do the models differ, does the GM's tie-breaking add
   value, is an overruled persona quietly right all season.
3. **Between-season prompt tuning.** A full season gives enough signal
   to see real tendencies. Mid-season tuning on a handful of points is
   how you fool yourself — see the sample size caveat below.
4. **Whether the council is worth it at all.** If Brand alone matches
   the council's counterfactual performance, five personas are theater
   with a bill attached. That is a genuinely interesting finding and it
   is invisible without this data.

#### What it cannot do

- It grades decisions *given* the strategy config. It says nothing
  about whether the config itself was set correctly.
- Waiver claims do not grade cleanly. The counterfactual there is "some
  player never rostered," not a specific evaluated alternative. Start/
  sit is where the measurement is honest; treat waiver attribution as
  soft.

#### The capture problem

Attribution data is only available at decision time. A week later,
rosters have changed, projections have been revised, and dropped players
may not be visible at all. Nothing here is reconstructable after the
fact — if the snapshot is missed, that week is permanently ungradeable.

New table, written during every run before anything is sent to Yahoo:

- `considered_options` — run id, persona, player_key, the action that
  was contemplated, projection value at that moment (both sources plus
  delta), std-dev, injury status, and whether this option was the one
  ultimately chosen.

This must capture **every option any persona evaluated**, not just the
recommended one. The bench player Belichuk rejected is exactly the
counterfactual needed later.

#### The three measures

Computed at scoring time (Tuesday results run), written to an
`attributions` table keyed by run id and persona.

- **Counterfactual points** — actual points of the chosen player minus
  actual points of the best alternative that was available and
  considered. Signed. Answers: did this decision gain or cost points.
- **Directional accuracy** — did the recommended option outscore its
  alternative, boolean. Crude but robust; a single 40-point outlier
  cannot distort it the way it distorts the points measure.
- **Calibration** — Brier score against the persona's stated
  confidence. Answers whether a persona knows when it is guessing,
  which is the question the entire council premise rests on.

Keep all three. They disagree in informative ways: a persona can be
directionally right most weeks while losing points overall, which means
it is right about coin flips and wrong about the ones that matter.

#### Per-persona grading

Every brief is graded independently against the same counterfactual,
whether or not the GM adopted it. Costs nothing extra — same snapshot —
and it is where the interesting findings live:

- A persona whose overruled recommendations were repeatedly correct
- Whether the GM's `unanimous_override` calls were justified
- Whether Taco's deliberately inflated confidence is *entirely* noise
  or occasionally tracks something
- Whether any of the five vendors is systematically better at this

Track `adopted` as a boolean on each attribution row so adopted and
overruled performance can be separated in queries.

#### Sample size caveat

A 17-week season yields roughly 10 start/sit decisions a week, so a few
hundred graded calls per persona at most — and far fewer inside any
single confidence band. Treat calibration numbers as directional, not
conclusive, and resist tuning prompts mid-season on the strength of a
handful of data points. The honest version of this analysis reports
sample size alongside every rate.

### 7.3 Trade policy and partner modeling — RESOLVES O-7

**The council has full autonomy on trades. No approvals from Ben, in
either direction.** It accepts, rejects, counters and initiates on its
own. This is deliberate: routing trades through a human approval step
would compromise the experiment and remove most of the entertainment.

#### Being gamed is a feature, with one exception

A league member who constructs a genuinely persuasive argument that
talks Muskett into a bad trade is the best possible outcome of this
project. That is protected — there is **no minimum projected-points
floor on accepting a trade**, and no quality guardrail of any kind.

What is not protected is a malformed offer slipping through on a
parsing bug. That ends the season in week 3 and produces no story.
Hence: **validity guardrails only.**

- Roster remains legal post-trade (size, position minimums)
- All player keys exist and are actually on the stated rosters
- Neither player is already involved in another pending trade
- Trade is within the league's trade deadline
- The offer parses cleanly into the expected structure

**When a validity guardrail blocks something the council wanted to do,
it says so in character** — Muskett or the GM notes that the front
office wanted this deal but IT/HR/Legal wouldn't clear it. Keeps the
blocked action visible and funny rather than a silent failure, and the
log page gets a running bit out of the compliance department.

#### Trade initiation pipeline

Needs-first, not opportunity-first. Ordering matters more than the
components.

The failure mode being avoided: if Muskett free-runs a "find good deals"
loop, he has no visibility into where the lineup is actually weak — that
is Belichuk and Brand's domain — so he surfaces trades that are
favorable but pointless. Worse, a model asked "who should we trade for"
reaches for players it remembers, which means famous names and whatever
was discussed recently rather than an actual survey of the league.

**Stage 0 — deterministic candidate generation. No model involved.**
Code computes our positional holes, bye-week gaps and surplus, does the
same for all eleven other rosters, and finds complementary pairs: our
surplus against their hole, their surplus against ours. Cheap,
exhaustive, unbiased. Produces ~20-40 candidate *shapes* before a single
token is spent. This step is what prevents the famous-names problem.

**Stage 1 — specialists brief on needs, not on trades.** Belichuk states
where the lineup is weak. Brand quantifies surplus and deficit against
rest-of-season projections. Taco flags who on other rosters looks
mispriced. None of them propose packages. The question is "what do we
need and what can we spare."

**Stage 2 — Muskett constructs and ranks.** He receives the
deterministic candidate list plus the needs briefs, builds actual
packages, and ranks them by projected improvement weighted by acceptance
likelihood from the partner model. He is the **only** persona doing
package construction — otherwise five models invent five different
trades and the GM is comparing apples to oranges.

**Stage 3 — GM selects** from the ranked slate, up to the weekly cap, or
selects none.

**Stage 4 — Muskett writes trade notes** for whatever was approved.

The expensive steps happen last by design. Package construction and note
writing only run on ideas that survived a free deterministic filter and
a cheap needs check.

**Cadence:** once weekly, Tuesday after waivers clear and rosters have
settled. Plus an event-triggered pass when a starter picks up a
significant injury designation — that is when a genuine need appears
mid-week, and waiting until the next Tuesday is too late.

Incoming offers stay on their own path: the 6-hour poll evaluates them
on arrival, independent of this pipeline.



There are **no deterministic quality floors anywhere in the trade path**
— not on accepting, not on initiating. Quality judgement belongs to the
council. The guardrails only enforce validity (see above).

But "no hard floor" is not "no assessment." Without a stated objective
the predictable failure is that Muskett optimizes for winning the
negotiation rather than improving the team — extracting value becomes
the measure of success, and the result is lopsided offers that get
rejected and a Negotiator who thinks that went well.

**On incoming offers.** The council assesses quality and decides. It may
accept a trade that looks unfavorable by projection — being talked into
something by a persuasive human is protected — but it must actually
evaluate rather than rubber-stamp. The assessment and the decision both
go in the log; if it accepts something bad, the reasoning for why is the
interesting artifact.

**On initiating.** The council generates a candidate slate, ranks it,
and takes the top N up to the weekly cap. Ranking criteria:

- Projected improvement over the remaining schedule, weighted by the
  horizon curve
- Whether it addresses an identified weakness — positional hole, bye
  gap, floor/ceiling mismatch against the current strategy setting —
  rather than just accumulating value
- Estimated probability of acceptance, from the partner model
- Cost of a rejection: the cooldown it would trigger with that manager

Rank by improvement weighted by likelihood of acceptance. That
naturally deprioritizes the lopsided offers that feel clever and never
get taken.

**Zero is a valid answer, and it is not a failure.** The council is
never obligated to fill its three slots. If nothing on the slate is
worth doing, it proposes nothing, records that it considered N options
and declined all of them, and moves on. State this explicitly in the
prompts — a model handed a cap will otherwise treat the cap as a
target.

Log the no-action decision with the same detail as an action. "We looked
at eleven trades this week and none of them were good enough" is a
legitimate outcome, an auditable one, and a funnier log entry than a bad
trade would be.

#### Offer expiry and withdrawal

Yahoo gives the recipient up to 10 days and notifies them by email plus
an alert on their team page. There is **no reminder or nudge endpoint**.
Cancelling a proposal is supported at any point before acceptance, so
self-imposed clocks are entirely our own mechanism.

- Every initiated offer carries a self-imposed expiry, minimum 24 hours,
  set by the council per offer.
- On expiry with no response: cancel the offer, free the pending slot,
  apply the no-response cooldown (7 days).
- Shorter clocks let the council run more than three ideas through a
  window without three dead offers blocking the slots for ten days.

**Nudging.** The only way to generate a second notification is
cancel-and-re-propose, which is functionally spam. Allowed at most once
per offer, and only when the partner model indicates that manager is
normally responsive. Otherwise let it expire. Every nudge is logged and
surfaces in the trade monitor.

#### Rate limiting

Two separate limits, and they interact:

- **Yahoo:** maximum 6 *pending* offers at any one time. Not per week.
- **Self-imposed:** maximum 3 *initiated* offers per week.

Three initiations sitting unanswered for the full 10-day window consume
half the pending slots and constrain the ability to respond to incoming
offers. The orchestrator must track pending count, not just weekly
count, and prioritize responses over initiations when slots are scarce.

#### Anti-spam, graduated by rejection type

Raw counts are the wrong control — three offers to three managers is
fine, three to one person is what gets you muted. Cooldowns key off
*how* the rejection happened:

| Rejection type | Cooldown before next offer to that manager |
|---|---|
| Immediate reject, no counter | 5-7 days |
| Reject after a counter exchange | 2-3 days |
| Negotiation that ran its course, no agreement | 0-1 days |
| No response at all until expiry | 7 days |

The reasoning: an immediate no-counter reject signals disinterest in
trading at all. A failed negotiation signals interest but disagreement
on terms, which is worth revisiting sooner.

**Similarity guard.** Independent of cooldown, block re-proposing an
offer substantially similar to one already rejected by that manager.
Compare on player sets rather than exact match — swapping a bench kicker
into a rejected offer does not make it a new offer. Deterministic check,
not a model judgement.

#### Horizon weighting

The council weights short-term against long-term value, where "long
term" means the rest of *this* season only. There is no next year.

The window is narrower than it appears: most Yahoo leagues set a trade
deadline around weeks 11-13, while fantasy playoffs run weeks 15-17.
There is no trade-for-the-playoff-push period — the deadline arrives
first. Long-term value therefore collapses to zero well before the
season does.

Inputs to the horizon curve, all deterministic and passed in the packet
rather than left to model inference:

- Weeks remaining until the league's actual trade deadline (read from
  league settings, not assumed)
- Projected seed, and playoff odds computed properly. At the current 8
  teams every team qualifies so odds are trivially 100%, but the league
  is expected to grow — compute them rather than special-casing the
  degenerate form
- Bye weeks remaining for each player in the proposed deal
- Weeks until fantasy playoffs begin

#### Trade partner modeling

Tracked per manager, and used by both the GM (choosing who to approach)
and Muskett (how to pitch).

**Structured, in `kb.db`:** response rate, median time to respond,
accept/reject/counter ratio, count of accepted offers that were
unbalanced by projection, current record, positional holes, upcoming
bye gaps, cooldown state.

**Qualitative, in `notes/managers/<pseudonym>.md`:** persona
observations accumulated over the season. This is the emergent-graph
case for the Obsidian layer — the council builds a scouting file on each
manager with no curation from Ben.

**Publication: private indefinitely.** Partner models do not appear in
the league-facing build or the public build during the season. After the
season ends, they may be published only with Ben's explicit approval,
per model.

Rationale: this is the one place where the AI being factually correct is
also unkind. "Manager 7 accepts unfavorable trades 40% of the time" is
accurate, useful, and mean — and pseudonymization does not help, because
the league knows who is who. It is also the closest thing the system has
to proprietary advantage, and publishing the council's full reasoning
already gives away most of the strategy.

Ben views partner models in Obsidian throughout the season. The static
site generator excludes `notes/managers/` from both builds
unconditionally; publishing requires a deliberate flag change, not just
an approval checkbox.

---

## 7.4 Failure handling and alerting — RESOLVES O-5, O-9

The operational floor from §1 is **never miss a lineup lock**. That is
only real if failures are noticed, and the dangerous failures here are
the quiet ones.

### Three failure classes

**Loud.** An API call errors, a model returns unparseable output, a
guardrail rejects everything. Detected, retried, alerted. Easy.

**Silent.** The timer never fired because the unit failed to load after
a reboot. The refresh token was invalidated and every call 401s. The
container ran, exited 0, and submitted nothing because an exception was
swallowed. Nothing errors and nothing alerts. This is the class that
loses a season, and alerting on failure never catches it.

**Deadline-bound.** The 11:45 lineup pass fails; retrying at 13:05 is
worthless because the games have started. Retries must fit inside the
window.

### Alerting

**Channel: push notification (Pushover or ntfy).** Not Slack — work
Slack on a Sunday morning is unreliable. Not email — it gets buried.

Severity tiers:

| Tier | Examples | Behaviour |
|---|---|---|
| P1 — immediate | Auth failure, lineup pass failed inside a lock window, dead-man switch tripped | Push immediately, repeat until acknowledged |
| P2 — same day | Waiver claim rejected, trade execution failed, guardrail blocked everything | Single push |
| P3 — digest | Individual model call failures that were retried successfully, similarity-guard blocks | Weekly summary only |

Alerts state what failed, what the current roster state is, and what
Ben can do about it. He is not obliged to act — but he should be able
to.

### No deterministic lineup fallback

**If the council cannot produce a lineup before kickoff, the existing
lineup stands and Ben is alerted. Nothing is auto-substituted.**

This is deliberate. A failure to decide is a council failure and it
carries its consequences, including the possibility of fielding a
player on bye for zero points. Substituting a silent non-council
lineup would protect points at the cost of putting a decision into the
record that no persona made — which corrupts attribution (§7.2) and
lets infrastructure failures hide behind a safety net.

Consequence accepted: a quiet infrastructure failure can cost a week
outright. That is the point.

**Manual intervention is permitted and logged.** An infrastructure
failure is not a council decision, so Ben stepping in is not a breach
of autonomy. Any week containing a manual intervention is flagged in
the ledger and excluded from persona attribution.

### Retry policy

- Retries are bounded by the lock window, not by a fixed count. Compute
  remaining time and retry until the window closes minus a safety
  margin.
- Individual specialist failures do not block the run. Proceed with the
  briefs that returned and record which personas were absent — a
  decision made by three of four is still a decision, and the ledger
  should know which one was missing.
- A GM failure does block. There is no decision without one.
- Never retry a submission that may have partially succeeded. Read
  current roster state back and reconcile before any second attempt.

### Dead-man switch

**External service (healthchecks.io style), not self-hosted.** A monitor
running on the VPS dies with the VPS, which is precisely the case it
exists to catch.

Critically: **ping on successful submission, not on process start.** A
container that runs and submits nothing must not ping. The check is
"did the intended change reach Yahoo," not "did the process execute."

Each scheduled run registers its own check with an expected window. A
missing ping alerts as P1.

### Token refresh — O-9

Yahoo refresh tokens can be invalidated without warning, and the failure
is silent: everything looks normal, nothing submits.

- Every run verifies auth before doing work, and treats a 401 as P1
  immediately rather than after exhausting retries.
- The token file lives on the mounted volume and is included in the
  nightly off-box backup.
- Reauthorization requires a browser and cannot happen unattended, so
  the alert must say so explicitly — this is one of the few failures
  that genuinely requires Ben at a keyboard.

### Failed runs are ledger records

A run that failed is written to `runs` with its failure mode, not
omitted. Attribution queries must be able to distinguish "the council
decided badly" from "the council never got to decide."

---

## 8. Guardrails



Deterministic, outside the models, between the GM decision and the
Yahoo API call. No model output bypasses them.

- Every `player_key` validated against live roster or FA pool
- No empty starting slots
- No player on bye in a starting slot
- No player designated Out in a starting slot
- Waiver claim never spends priority below the configured floor
- Trade never reduces projected starting points without an explicit
  `override_reason`
- Reject the entire brief on a malformed key — do not retry blind
- Every rejection logged; repeated failures are a prompt problem

---

## 9. Web surfaces

### 9.1 Pseudonymization at ingest

**Real identities never enter the system.** The Yahoo client maps
manager names and team names to stable pseudonyms at the API boundary,
before anything is stored or sent to a model. The mapping table lives in
a single file outside `kb.db` and outside `notes/`, and is never included
in any packet.

This is the deterministic guarantee. A filter applied at render time can
be defeated by a persona referring to someone obliquely; a model that
never saw a real name cannot emit one. Everything downstream — briefs,
notes, wikilinks, the log page — is pseudonymous by construction.

Team names get mapped too, not just manager names. Fantasy team names in
a work league are often inside jokes that identify their owner more
reliably than the owner's name does.

Build-time backstop: fail the static site build if any string from the
mapping table appears in the rendered output. Belt and braces, but the
failure mode is publishing a colleague's name, so it earns its keep.

### 9.2 Two log sites

**Private (league)** — full detail, real pseudonym-to-person mapping
implicit because the league knows who is who. Gated by Cloudflare Access
on an allowlist of league members. This is the entertaining one.

**Public (LinkedIn-facing)** — the same static generator with team and
manager references rendered as pseudonyms, published openly. This is the
one to link from a post about the experiment.

Both are static builds from the same `kb.db`, so the marginal cost of
the second site is a build flag.

### 9.2.1 Publication approval

The public build is **opt-in per run**, not a global flag. `kb.db` gets a
`publish_approved` boolean on `runs`, defaulting to false. The public
generator renders only approved runs; the private site renders
everything.

Workflow:

1. Weeks 1–3 run private only. Nothing is published.
2. The league reviews the private site — real content, real trade notes,
   their own words included.
3. They approve or deny. Denial can be per-run rather than all-or-
   nothing, so one awkward exchange doesn't sink the whole idea.
4. Approved runs backfill into the public build; subsequent weeks
   default to approved unless someone objects.

Trade notes **are** included in the public build. They are the most
entertaining artifact the system produces and the league has seen them
before anything ships. Note that a trade exchange contains the other
manager's words as well as Muskett's — approval from that specific
manager is what makes publishing their side fine.

Pseudonymization stays regardless of approval. It costs nothing, and an
outside audience gains nothing from real names.

A per-run `publish_denied_reason` field is worth having. If someone
denies a run, knowing why is more useful than a silent false.

`X-Robots-Tag: noindex, nofollow` on the private site. The public site
is meant to be indexed.

### 9.3 Admin console — RESOLVES O-4

**Cloudflare Tunnel to a FastAPI service on the VPS.**

`cloudflared` runs as a second container holding an outbound connection
to Cloudflare's edge. Nothing listens on a public port and the firewall
stays closed. FastAPI binds `127.0.0.1:8000` only. `admin.<domain>`
routes down the existing tunnel to that local port. Cloudflare Access
sits in front with a single-email policy, so unauthenticated requests
never reach the box. Same shape as nhi-docs without the Pages layer.

The app reads `kb.db` for statistics and reads/writes `strategy.json`
for the knobs. The engine picks up config changes on its next run —
nothing restarts.

**Sections:**

- **Season summary** — record, projected seed, cumulative counterfactual
  points, GM override count
- **Council accuracy** — per persona: hit rate, counterfactual points,
  calibration. **Sample size shown alongside every rate** (§7.2)
- **Knobs** — variance, waiver aggression, waiver priority floor, trade
  initiations per week, cooldown lengths, similarity threshold, season
  mode, autopilot
- **Trade monitor** — see below
- **Health** — last run, next run, token expiry, dead-man switch state,
  API spend to date

**Trade monitor.** Trade spam is the failure mode most likely to need
in-season correction, and it is only visible in aggregate:

- Offers initiated this week against the cap; pending count against
  Yahoo's 6
- Per-manager: offers sent, rejections by type, current cooldown state
  and when it expires
- Similarity-guard blocks, with what was blocked and against what
- Full negotiation threads, since a drawn-out exchange reads very
  differently from a single offer
- Validity-guardrail trips, with the in-character note that was logged

Cooldown lengths, the weekly initiation cap, and the similarity
threshold all live in `strategy.json` and are tunable mid-season without
a redeploy. Expect to tune them.

**Every knob change is written to the ledger with a timestamp.** A
strategy change mid-season is a confound for attribution; unrecorded, it
is an invisible one.

**Read-only fallback.** Stats and the trade monitor also render into the
private log site as static pages. If the tunnel is down, monitoring
survives — only knob-writing is lost, and that falls back to editing
`strategy.json` over SSH.

### 9.4 Decision log detail

Per-run view showing all briefs side by side, the GM verdict, what was
overruled, and the outcome once known. Rendered directly from `kb.db`
records.

---

## 9.5 Build and deploy — RESOLVES O-10

No CI service. Overkill for a single-user seasonal project.

**Local:** development in containers on the workstation. Git for
history, GitHub for tracking, PRs for every change, **squash merge to
main**. Squash merging matters more than usual here — it makes main a
linear list of deployable commits, so one commit maps to one `deploys`
row with no ambiguity about what shipped.

**Deploy:** SSH to the VPS from Cursor. A `deploy.sh` on the box does
the work; the agent runs the script rather than improvising commands.

Deploy script, in order:

1. Refuse if inside the freeze window (Thu 17:00 – Mon 23:59 ET) unless
   `--emergency` is passed explicitly
2. `git pull` on main
3. Build tagged: `podman build -t ci:$(git rev-parse --short HEAD)`
4. Run any schema migration
5. Retag `ci:current` to the new image, restart the timer units
6. Write a `deploys` row: timestamp, SHA, description, whether decision
   logic was touched
7. Run a dry-run pass and fail loudly if it does not complete

**Rollback keeps the last five images.** Rollback is retagging
`ci:current` to a previous SHA, **not rebuilding** — a rebuild can fail
or produce something different if a dependency moved, and 11am Sunday is
the worst possible time to discover that. `deploy.sh --rollback <sha>`
should be a single command that works without network access.

### Runtime state is not in the repo

`strategy.json`, `kb.db`, `notes/` and the token file live on the
mounted volume at `/srv/ci/`, **outside the git working directory**. A
`git pull` or a rebuild must never be able to touch them.

This is the sharpest footgun in the whole deployment story: if runtime
state sits inside the repo directory, a checkout, a stash, or a clean
silently destroys the season's attribution data. Keep them separate and
verify the separation before week 1.

### Cursor with SSH access to production

An agent with root on the live box during the season is a real risk,
and the mitigations are in `.ai/rules.md`:

- The agent runs `deploy.sh`; it does not hand-edit files on the VPS.
  Anything done directly on the box is config drift that will not
  survive the next deploy and will not be in the repo.
- Infrastructure changes go through the same PR and documentation flow
  as application code.
- Secrets are set on the box once, manually, as podman secrets. They are
  never in the repo, never in an image, and never regenerated by an
  agent.

---

## 10. Open questions

Tracked in §11 with detail. Summary:

- O-1 ~~Success criteria and autopilot at season start~~ **RESOLVED** — see §1
- O-2 ~~Draft approach~~ **RESOLVED** — see §3
- O-3 ~~Monday night and mid-week lineup edge cases~~ **RESOLVED** — see §5
- O-4 ~~Strategy UI hosting~~ **RESOLVED** — see §9.3
- O-5 ~~Failure handling and alerting~~ **RESOLVED** — see §7.4
- O-6 ~~Projection data source~~ **RESOLVED** — see §3.1
- O-7 ~~Trade authority limits~~ **RESOLVED** — see §7.3
- O-8 ~~Outcome attribution / counterfactuals~~ **RESOLVED** — see §7.2
- O-9 ~~Secrets and token refresh failure~~ **RESOLVED** — see §7.4
- O-10 ~~Build and deploy pipeline~~ **RESOLVED** — see §9.5
- O-11 Season-end and archival

---

## 11. Decision log

Decisions made so far, with the reasoning, so future-me knows why.

| # | Decision | Rationale |
|---|---|---|
| D-1 | Yahoo Fantasy API v2, Read/Write | Only option; lineups and transactions are writable |
| D-2 | Draft is advisory, not automated | No draft-pick endpoint exists |
| D-3 | Python app in Podman | Mature Yahoo wrappers; matches current stack |
| D-4 | Vultr shared CPU VPS | Decouples Sunday uptime from home ISP |
| D-5 | systemd timers over cron | Logging, oneshot semantics, failure visibility |
| D-6 | Cloudflare Pages + Access | No inbound ports; pattern already in use |
| D-7 | OpenRouter for multi-vendor | One key, one schema, all vendors |
| D-8 | Council of 5 + 1 cosmetic | Comedy and genuine perspective diversity |
| D-9 | Structured briefs, not chat | Free-form agent chat drifts into agreement theater |
| D-10 | Personality quarantined to `voice_line` | GM needs parseable reasoning |
| D-11 | Dual KB: SQLite + markdown | Two access patterns: aggregation vs. wholesale read |
| D-12 | No vector store | Season fits in context; nothing to retrieve against |
| D-13 | Deterministic guardrails post-GM | Model output never reaches Yahoo unvalidated |
| D-14 | Lightly distorted names for real people | Avoids misattribution; parody read stays obvious |
| D-15 | Lasso outside decision path | Keeps him funny; prevents sentimental starts |
| D-16 | Obsidian as a vault over `notes/`, on workstation only | Zero architectural cost; explicit learning objective |
| D-17 | Pseudonymize managers and team names at ingest | Deterministic — a model that never saw a name cannot emit one |
| D-18 | Two log sites, private and public, same generator | Public post possible without exposing colleagues |
| D-19 | Public build opt-in per run, league reviews first | Real artifacts beat hypothetical objections; trade notes stay in |
| D-20 | FantasyPros primary + Tank01 secondary for projections | ~$95-100/season; source disagreement is signal, not noise |
| D-21 | Std-dev wired directly to the variance knob | Deterministic link beats hoping the model infers it |
| D-22 | Record all three attribution measures | They disagree informatively; cheap to compute from one snapshot |
| D-23 | Grade every persona, including overruled briefs | Same snapshot, no extra cost; overruled-but-right is the key finding |
| D-24 | `considered_options` snapshot written before execution | Counterfactuals are unrecoverable after the week closes |
| D-25 | Full council autonomy on trades, no approvals | Experiment integrity; being out-negotiated by a human is a good outcome |
| D-26 | Validity guardrails only, no deterministic quality floor anywhere | Judgement belongs to the council; guardrails block bugs, not bad calls |
| D-32 | Candidate slate ranked by improvement × acceptance likelihood | Deprioritizes clever lopsided offers that never get taken |
| D-33 | Zero trades is an explicit valid outcome, logged like any other | A model handed a cap will otherwise treat the cap as a target |
| D-34 | Self-imposed offer expiry, min 24h, then auto-withdraw | Frees pending slots; dead offers shouldn't block the window |
| D-35 | Nudge only via cancel-and-repropose, once per offer, responsive managers only | No reminder endpoint exists; the workaround is indistinguishable from spam |
| D-36 | Needs-first initiation pipeline, deterministic candidates first | Prevents favorable-but-pointless trades and famous-name bias |
| D-37 | Muskett alone constructs packages | Five models inventing five trades makes the GM compare apples to oranges |
| D-38 | Trade notes signed `"E" Muskett [xAI]` | Names the persona and the vendor, not a generic AI disclosure |
| D-39 | Criteria ranked: entertainment > decision quality > win rate > experiment integrity | Explicit tie-breaking; shapes variance defaults and persona tuning |
| D-40 | Entertainment never licenses deliberately bad play | Violates #2, and stops being funny by week 3 |
| D-41 | Never miss a lineup lock — operational floor outside the ranking | Costs nothing against any criterion; the one genuinely embarrassing failure |
| D-42 | Full autonomy from week 1, no propose-mode warm-up | Early mistakes are content; a human in the loop pollutes the cleanest attribution data |
| D-43 | Live advisory + pre-rank fallback for the 6 Sep draft | Adaptive where it matters; sheet covers disconnection |
| D-44 | Council recomputes after every pick, not on our clock | ~15 min between our picks; removes all latency pressure |
| D-45 | Draft assistant built standalone, not on the season engine | 10 days; needs no KB, guardrails, site, or VPS |
| D-46 | Rehearse the polling loop against a Yahoo mock draft by day 6 | Only way to verify endpoint freshness before it matters |
| D-47 | League settings + scoring table pulled at every run, diffed and logged | Mid-season rule changes propagate; silent changes invalidate projections |
| D-48 | Projections computed from stat lines using league scoring | No published source uses this scoring; QB values are ~3x standard |
| D-49 | Draft output is a ranked list of 5+, never a single pick | 1-minute clock plus snake turn means back-to-back picks |
| D-50 | Waiver resource is priority position, not FAAB | This league uses a continual rolling list |
| D-51 | Team count read at runtime; nothing derived from it hardcoded | League is 8 now, expected to grow to 10-12 |
| D-52 | Playoff odds computed properly, allowed to degenerate to 100% | Special-casing the 8-team form breaks when the 10th manager joins |
| D-53 | Negotiator weights veto probability, scaled by team count | Veto is impossible at 8 teams, a bare majority at 12 |
| D-54 | Waiver claims submitted Monday evening, not at Tuesday processing | A run at processing time misses the window |
| D-55 | Daily rolling-waiver pass, deterministic pre-check before any model call | Rolling list clears players off-cycle all week |
| D-56 | Five-plus lineup passes per week, one per lock window | Players lock individually at kickoff, not weekly |
| D-57 | Every lineup pass scheduled after the relevant inactive report | Inactives post 90 min before kickoff and routinely change the call |
| D-58 | Same specialist panel for every lineup pass | Decision type sets the panel; the Thursday exclusion was arbitrary |
| D-59 | Alerts via push notification, not Slack or email | Sunday morning reachability |
| D-60 | No deterministic lineup fallback — existing lineup stands | Failure to decide is a council failure with real consequences; protects attribution |
| D-61 | Manual intervention permitted, logged, excluded from attribution | Infrastructure failure is not a council decision |
| D-62 | External dead-man switch, pinged on submission not on start | A self-hosted monitor dies with the box; process start proves nothing |
| D-63 | Failed runs written to the ledger with failure mode | "Decided badly" and "never decided" must be distinguishable |
| D-64 | No Thursday margin rule; packet states the option-value asymmetry instead | Judgement stays with Belichuk, but the asymmetry isn't visible in projections |
| D-65 | Late passes receive live matchup state and override weekly variance | Needing a miracle and protecting a lead are different problems |
| D-66 | IR moves automated in the waiver pass; activation-with-drop reasoned normally | Humans forget IR; freeing a roster spot is nearly free value |
| D-67 | Admin console via Cloudflare Tunnel + Access, FastAPI bound to localhost | No inbound ports; matches the nhi-docs pattern |
| D-68 | Every knob change written to the ledger with a timestamp | A mid-season config change is a confound; unrecorded it is an invisible one |
| D-69 | Stats and trade monitor also render statically into the private log site | Monitoring survives a tunnel outage |
| D-70 | No CI service; SSH deploy via `deploy.sh`, PRs and squash merge to main | One commit per change maps cleanly to one deploys row |
| D-71 | Images tagged by SHA, last five kept; rollback retags, never rebuilds | A rebuild can fail or drift at the worst possible moment |
| D-72 | Runtime state on the volume, outside the git working directory | A checkout or clean would otherwise destroy the season's data |
| D-73 | Freeze window enforced by the deploy script, not by discipline | The rule only works if the tooling holds it |
| D-74 | `season_id` stamped on runs, deploys and config changes from the first write | Keeps the O-11 carry-forward decision available; a December migration otherwise |
| D-27 | Blocked actions announced in character as IT/HR/Legal | Keeps failures visible and funny instead of silent |
| D-28 | 3 initiations/week, cooldowns graduated by rejection type | Per-manager frequency is the real annoyance vector, not raw count |
| D-29 | Deterministic similarity guard on re-offers | Model judgement is the wrong tool for a repetition check |
| D-30 | Horizon curve keyed to actual trade deadline + playoff odds | Deadline precedes playoffs; long-term value hits zero early |
| D-31 | Partner models private indefinitely, post-season publish only with approval | Accurate and unkind; also the only proprietary edge left |
| D-75 | UNS/MQTT adopted as the current-state bus; `kb.db` stays the record | Walker Reynolds' pattern as an IIoT learning vehicle; the dashboard's "now" panels fit retained topics, historical aggregations do not |
| D-76 | Engine writes `kb.db` first, then publishes best-effort | A broker outage must not lose attribution data or block a Yahoo submission; `considered_options` is unrecoverable if skipped |
| D-77 | Enterprise MQTT root is `confidently-incorrect/<season_id>/…` | Full team name at the enterprise level; `ci` stays the image tag and `/srv/ci/` volume only |
| D-78 | Broker WebSocket listener binds localhost; Access via the existing Cloudflare Tunnel | Preserves D-67 — no inbound ports on the VPS |
| D-79 | Payloads are UTF-8 JSON, not Sparkplug B | Human-readable on the log-reading path; Sparkplug's device model does not fit oneshot council runs |
| D-80 | Claude Fable implements every UI/UX surface | Parent agents freeze the contract and stay off the pixels; Fable is the specialist for layout, interaction, and frontend |
| D-81 | Thin Yahoo Fantasy v2 client (OAuth 2.0 + httpx), no third-party wrapper | 401 must raise immediately (O-9) and tokens must live on the state volume; a wrapper hides both. App credentials and the token file are `$CI_STATE_DIR/tokens/yahoo-app.json` and `yahoo.json`. 403 / `additional_authorization_required` is an access-program error, not an auth failure. |
