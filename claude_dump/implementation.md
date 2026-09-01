# Confidently Incorrect — Implementation Plan

Companion to `architecture.md` (design decisions) and
`council-prompts.md` (persona prompts + schema).

This document is the build order and the operational notes. Architecture
answers "what and why"; this answers "in what order, and what will bite."

**Hard deadline: draft Sunday 6 September 2026, 20:00 EDT.** Room opens
19:30. Ten days from 27 August.

---

## 0. League facts (verified from settings, 27 Aug 2026)

| Setting | Value | Consequence |
|---|---|---|
| Teams | **8 confirmed, 2+ more likely, cap 12** | Fluid — derive everything, hardcode nothing |
| Playoff teams | 8 | At 8 teams everyone qualifies; at 10+ there is a real race |
| Playoff weeks | 15, 16, 17 | Reseeding on; higher seed wins ties |
| Draft | Live Standard, 6 Sep 20:00 EDT | Snake |
| Pick clock | **1 minute** | Back-to-back picks at the turn |
| Roster | QB, WR, WR, RB, RB, TE, W/R/T, K, DEF, 6×BN, 2×IR | 9 starters, 15 active |
| Rounds | 15 | 120 picks total |
| Scoring | Head-to-head, heavily customized | See §0.1 |
| Fractional points | **No** | Scores are integers; projections round |
| Waivers | Continual rolling list, 2-day | **No FAAB.** Priority is the resource |
| Waiver run | Game Time — Tuesday | |
| Max acquisitions | No maximum | Aggressive churn is free except for priority |
| Trade deadline | 28 Nov 2026 | ~Week 12 — verify against NFL schedule |
| Trade review | League vote, 6 to veto, 2 days | Veto difficulty depends on team count — see §0.2 |
| Draft pick trades | No | N/A after draft |
| Post-draft players | Follow waiver rules | Undrafted go to waivers, not free agency |
| IR adds from FA/waivers | Not allowed directly | Guardrail |

### 0.2 Team count is not fixed — derive, do not hardcode

8 teams are confirmed, at least 2 more are expected, and the league may
keep growing. Every quantity below must be **computed from the live team
count** read via the API, not written as a constant.

| Quantity | At 8 | At 10 | At 12 |
|---|---|---|---|
| Playoff race | None — all qualify | 2 miss | 4 miss |
| Votes to veto, as share of non-participants | 6 of 6 — unanimous | 6 of 8 | 6 of 10 — bare majority |
| Rostered players (15 each) | 120 | 150 | 180 |
| Waiver wire depth | Deep | Moderate | Thin |
| Gap between our picks | ~7 min | ~9 min | ~11 min |

Consequences:

- **Playoff odds:** compute them properly. If the league stays at 8 they
  degenerate to 100% harmlessly. Do not special-case the degenerate
  form — that is a bug waiting for the tenth manager to join.
- **Veto risk:** at 8 teams a veto needs every uninvolved manager and is
  effectively impossible. At 12 it is a bare majority and genuinely
  plausible. The Negotiator should weight veto probability when
  constructing lopsided offers, and that weight must scale with team
  count.
- **Waiver aggression:** thinner wire as the league grows argues for
  lower default aggression. Wire priority is worth more when there is
  less on the wire.
- **Draft timing:** larger league means longer gaps between our picks,
  which only makes background recompute more comfortable. The
  back-to-back picks at the turn are unaffected — the ranked-list
  requirement holds at any team count.

If teams are still being added close to 6 September, the draft tool must
read the team count and pick order at draft start rather than at build
time.

### 0.1 Scoring deltas that actually matter

Custom values diverging from Yahoo defaults, with impact:

- **Completions: 1 point** (default 0). Enormous QB inflation.
- **Passing yards: 15 per point** (default 25). More QB inflation.
- **Passing TD: 6** (default 4). More again.
- **Receptions: 1** (default 0.5). Full PPR — volume receivers gain.
- **Sack: 3** (default 1). DST with pass rush is a real asset.
- **DST return yards: 20 per point** (default 0). Return game matters.
- **FG 50-59: 5, 60+: 6** (default 0 for both). Big-leg kickers.
- **Missed FG and missed PAT carry penalties** (defaults 0).

**Worked comparison.** QB with 25 completions, 300 yards, 3 TD:
25 + 20 + 18 = **63 points**. Same line under standard scoring: ~24.
A strong RB week (100 yds, 1 TD, 4 rec): 10 + 6 + 4 = **20**.

**Elite QBs score roughly 3× what skill players do in a single-QB
league.** Draft accordingly, regardless of published ADP.

**Ambiguity to resolve:** "Negative Points: No" appears alongside
explicitly negative values (INT −1, fumbles lost −2, missed FG −3/−4,
missed PAT −1). Likely means a player's total floors at zero rather
than that penalties are disabled. **Verify with the commissioner before
draft day** — it changes how much a turnover-prone QB should be
discounted.

### 0.2 Projections must be recomputed

No published projection source uses this scoring. Pull **stat-level**
projections (FantasyPros returns full stat lines) and apply the league
scoring table in our own code. Never consume a source's fantasy-point
column directly.

Round to integers to match "fractional points: no".

---

## 1. Critical path to 6 September

Ordered by risk, not by logical sequence. Do the risky thing first.

### Day 1-2 — OAuth end to end

The single most likely thing to consume the schedule. A new API's auth
dance always takes longer than expected.

- Register the Yahoo app with Fantasy Sports **Read/Write**
- One-time browser authorization on the workstation, `redirect_uri=oob`
- Persist the token file; verify refresh works unattended
- Smoke test: read own team, read league settings, read a roster

**Gate:** if OAuth is not working by end of day 2, cut live advisory
and ship the cheat sheet only.

### Day 2-3 — League settings and scoring ingestion

- Pull league settings and the full scoring table from the API
- Build the scoring engine: raw stat line → league points
- Validate against a known past week if any data is available

### Day 3-5 — Projections and tiers

- FantasyPros subscription and API access
- Pull stat-level season and weekly projections for all relevant players
- Apply league scoring; rank
- Build positional tiers and identify tier breaks
- Compute ADP delta (published ADP vs our value ranking) — this is where
  the QB inflation will show up as a large exploitable gap

### Day 5-6 — Draft loop skeleton

- Poll draft results endpoint; compute available pool
- Render a local page: available by tier, our roster so far, our next
  pick number
- **Works with no models involved.** This alone is a usable draft tool.

### Day 6 — Mock draft rehearsal

Join a Yahoo mock draft and run the polling loop live.

Questions it answers, none of which are answerable from documentation:
- Does the draft results endpoint update within seconds, or lag?
- What shape does it return mid-draft vs post-draft?
- Does it rate limit under a 5-second poll?

**Gate:** if polling is unusable, fall back to manual pick entry. Build
the keyboard entry path on day 7 if so.

### Day 7-8 — Council integration

- Belichuk, Brand, Taco → Maddox, on the draft packet
- **Output must be a ranked list of 5+, not a single pick** (see §2.1)
- Recompute in background after every pick by anyone
- Fall through to tier-based best-available on any model failure

### Day 9 — Pre-rank sheet

Generate top ~200 by our scoring, enter manually into Yahoo's pre-rank
tool. No API for this. Budget 60-90 minutes of tedium.

Worth doing even if the live tool works perfectly. It is the net that
catches a dropped connection at pick 4.

### Day 10 — Dry run and buffer

Full rehearsal against another mock. Fix whatever broke.

---

## 2. Draft-day operational notes

### 2.1 The turn problem

8-team snake. At the turn (picks 8 and 9, 16 and 17, etc.) two picks
come back to back with a 1-minute clock and no meaningful gap.

**Requirement: the council always outputs a ranked list of at least 5
candidates, never a single recommendation.** At the turn, take 1 and 2
from the same list. Recompute after.

Between-turn gaps are ~7 picks × 60s ≈ 7 minutes, which is ample for a
full background recompute.

### 2.2 Fallback ladder

1. Model call fails or times out → tier-based best available from the
   precomputed list, no model
2. Polling stalls → manual keyboard entry of picks made
3. Connection drops → Yahoo autopick follows the pre-rank sheet
4. No sheet entered → Yahoo's own default rankings (survivable, worse)

### 2.3 Do not build for draft day

No SQLite ledger, no Obsidian, no log site, no VPS, no guardrails
framework, no trade logic, no Muskett, no strategy UI. The draft
assistant runs on the workstation and most of it gets thrown away.

Muskett is idle — nothing to negotiate during a draft. Lasso writes an
opening note at 20:00 and a closing one at the end.

---

## 3. Post-draft build order

Season engine, no hard deadline but week 1 kicks off ~10 September.

1. **Never miss a lock** — the lineup path end to end, guardrails
   included, before anything else. This is the operational floor from
   architecture §1.
2. `kb.db` schema and the `considered_options` snapshot. Attribution
   data is unrecoverable if this lands late (architecture §7.2).
3. Waiver path — **rewritten for rolling priority, not FAAB** (§4.1)
4. Trade path, including the 2-day league-vote review window
5. Log site generation and Cloudflare Pages push
6. Strategy UI and trade monitor
7. `notes/` and the Obsidian layer

---

## 4. Corrections to architecture.md

Found while checking the design against actual league settings.

### 4.1 FAAB does not exist in this league

Waivers are a **continual rolling list**. There is no bidding budget.

- Remove the FAAB cap from `strategy.json` and from the guardrails
- The resource is **waiver priority position**. Claiming drops you to
  last in the order
- Model it explicitly: current position, who is ahead, what claiming
  costs in future priority
- "Waiver aggression" as a knob now means willingness to spend
  position, not willingness to bid

With 8 teams and no acquisition cap, the wire is deep and churn is
nearly free — the only cost is priority. That likely argues for more
aggression than a 12-team FAAB league would.

### 4.2 Playoff odds are conditional, not useless

At the current 8 teams, all of them make the playoffs and odds are
always 100%. With 10 or 12 teams there is a real race.

**Compute playoff odds properly and let them degenerate.** Do not
replace or special-case them. Add **projected seed** alongside, which
carries information at every league size — reseeding is on, so seeding
decides matchups in weeks 15-17.

Note the interaction: the trade deadline (~week 12) precedes the
playoffs, so the council must acquire playoff-week strength before it
can see the playoff bracket.

### 4.3 Trades are not final on acceptance

Two-day review, league vote, 6 votes to veto. With 8 teams and 2 in the
trade, 6 others remain — a veto requires all of them. Practically
impossible, but:

- `executions` must track a pending review state, not just accepted
- A trade can be reversed after the council believed it succeeded
- Roster planning must not assume a traded player is available until
  review clears
- The 2-day window overlaps the Tuesday waiver run in some cases

This is also an accidental safety net on the being-gamed-is-a-feature
policy: a genuinely egregious fleece can be voted down by the league.

### 4.4 Scoring table must be a runtime input

Confirmed as the right call. Pull league settings and the full scoring
table at the start of **every** run, pass them in the packet, and diff
against the previous run. Log any change loudly — a mid-season scoring
change that goes unnoticed silently invalidates every projection.

### 4.5 Integer scoring

"Fractional points: No" means counterfactual attribution granularity is
whole points. Round projections to integers so predicted and actual are
on the same scale.

---

## 5. Open items on the critical path

- Confirm the "Negative Points: No" interpretation with the commissioner
- Verify FantasyPros returns stat-level projections on the tier
  purchased, not just fantasy point totals
- Map the 28 Nov trade deadline to an NFL week number against the actual
  2026 schedule
- Confirm final team count before 6 September; re-check draft position
  and round count if it changes
- **Resolve "Lock Benched Players: No".** If benched players genuinely
  do not lock at their kickoff, late-window swaps have far more freedom
  than assumed and the lineup pass schedule should exploit it. Verify
  the actual behaviour in week 1 rather than reasoning about the setting
  name.
- **Confirm Yahoo's exact weekly waiver processing time** for this
  league. The Monday-evening submission window is built on an
  assumption; if processing runs earlier than expected the claims miss.
  Verify in week 1 by submitting a low-stakes claim and watching when it
  resolves.
- Confirm whether Yahoo's draft results endpoint is available and fresh
  during a live draft (mock draft rehearsal, day 6)
