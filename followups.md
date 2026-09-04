# Confidently Incorrect — Follow-Ups Register

The single list of things that need checking, confirming, or doing
outside of writing code. If it needs verification and isn't here, it
will be forgotten.

Companion to `architecture.md` (decisions), `implementation.md` (build
order), `council-prompts.md` (personas).

**How to use this:** when an item is resolved, do not delete it — write
the answer into the Resolution column and leave it. A struck-through
item with a recorded answer is worth more than a missing one, because
the next surprising behaviour will send you looking for what was already
checked.

Status key: ☐ open · ☑ resolved · ⚠ blocked or overdue

---

## A. Before draft — Sunday 6 September 2026, 20:00 EDT

Ten days. These gate the draft working at all.

| # | Status | Item | Why it matters | How to check | Resolution |
|---|---|---|---|---|---|
| A-1 | ☐ | OAuth working end to end, token refresh unattended | Everything depends on it. Day-2 gate: if not working, cut live advisory | Read own team, league settings, a roster. Restart the process and confirm refresh | Client shipped (`python -m yahoo authorize` / `smoke`). Unit tests cover persist, refresh, and 401. **Live smoke still required** and is blocked on A-12. **2 Sep 2026:** draft path no longer waits on this — Ben transfers settings/picks by hand (issues #4, #9). Season still needs A-1. |
| A-2 | ☑ | Does the FantasyPros tier purchased return **stat-level** projections, not just point totals? | League scoring is heavily custom. Point totals from any source are useless here | Inspect an actual API response before committing to the subscription | **2 Sep 2026:** Live `GET /public/v2/json/nfl/2026/projections` returns full stat lines (`pass_yds`, `rush_yds`, `rec_rec`, …) plus `points*` we ignore. Not points-only. Regenerated HOF key is `tier=premium` and returns the full pool (A-14). K is `fg`/`fga`/`xpt` only. Week-1 DST has `def_pa`/`def_tyda`; week-0 DST does not. `rank_std` is on consensus-rankings, not projections. |
| A-3 | ☐ | FantasyPros billing — monthly available, or annual only? | $45 vs ~$108 for the season | Check at signup | |
| A-4 | ⚠ | Is Yahoo's draft results endpoint available and fresh **during** a live draft? | The entire live advisory design assumes it. No documentation answers this | Join a Yahoo mock draft, run the polling loop. **Do by day 6** | **2 Sep 2026:** draft night uses manual pick entry instead of polling (issue #9). Leave open if/when API access returns; not on the draft critical path. |
| A-5 | ☐ | Final team count | 8 confirmed, 2+ expected. Changes draft position, round count, playoff race, veto threshold | Confirm with commissioner the day before | |
| A-6 | ☐ | "Negative Points: No" — does it disable penalties, or floor a player's total at zero? | Settings list explicit negatives (INT −1, fumble −2, missed FG −3/−4). Changes how much to discount turnover-prone QBs, and QBs dominate this scoring | Ask the commissioner | Engine (D-84) currently applies signed category points as written; no floor, no stripped penalties. Interpretation still unconfirmed. |
| A-7 | ☐ | Pre-rank sheet entered into Yahoo | Outermost fallback if the connection drops mid-draft. No API — manual entry, 60–90 min | Day 9 | |
| A-8 | ☐ | Tell the league it's AI-managed and that a public version is planned | Consent is cheap now, awkward in October | One Slack message | |
| A-9 | ☐ | Verify runtime state at `/srv/ci/` is outside the git working directory | A checkout, stash, or clean would destroy the season's attribution data. Sharpest footgun in the deploy story | Run `git clean -nxd` on the VPS and confirm nothing under `/srv/ci/` is listed | Local layout uses `CI_STATE_DIR` outside the worktree. **VPS check still open.** |
| A-10 | ☐ | Verify `deploy.sh --rollback <sha>` works without network access | Rollback is the Sunday-morning escape hatch. Untested, it isn't one | Roll back and forward once on the VPS before week 1 | |
| A-11 | ☑ | Stamp every `kb.db` record with a season identifier | The only part of O-11 that is expensive to retrofit | — | **Resolved in design.** `season_id` on `runs`, `deploys`, `config_changes`; child tables inherit via run id. `notes/` front matter carries it too. See architecture §7.1 |
| A-12 | ☐ | Yahoo Fantasy API access program approval | Since ~2026-07-22 the self-serve Fantasy permission is gone. New apps 403 / `additional_authorization_required` even when OAuth mints a token. Review is 1–2 weeks and some applicants have waited a month. If this is not approved before 6 Sep, the Day-2 gate fires and live draft advisory is cut. | Apply at https://sports.yahoo.com/developer/access/ with any existing App ID. Do **not** delete and recreate the app — the create form no longer offers Fantasy Sports. Diagnostic: refresh_token grant returns 200 but `/fantasy/v2/game/nfl` returns 403 → Yahoo authorization, not local credentials. | **2 Sep 2026:** API is in limbo; application may stay in Yahoo's queue. Draft proceeds without it (manual settings + picks). If denied for the season, considering a logged-in session / site-request replay for writes (not decided). See architecture D-83 (settings file) and D-85 (manual draft). |
| A-13 | ☑ | Do FantasyPros kicker and DST lines cover this league's scoring? | FG distance bands, miss penalties, DST return yards (20/pt), and blocks are scoring deltas | Live projections for K and DST, week 0 and week 1 | **2 Sep 2026:** No. K is `fg`/`fga`/`xpt`. No `dst_return_yd` or `dst_blk`. Week-1 DST has `def_pa`/`def_tyda`; week-0 does not. Skill-position lines are complete. Issue 8 must not treat K/DST FP lines as full league scores. See D-86. **2 Sep 2026 (D-88):** pool flags those lines `scoring_incomplete` and keeps them out of the ADP-gap list. |
| A-14 | ☑ | FantasyPros HOF key actually untruncates the pool | Draft sheet needs every relevant player, not the free-tier 10 | `python -m data fantasypros-smoke` exits 0; response `tier` is not `free` | **2 Sep 2026:** Regenerated key is `tier=premium`. Live smoke: week0=571, week1 QB=86, RB rankings=181, injuries=241. `public_api_limited` stays true on HOF and is not a page cap — truncation is `len(players) < count`. |
| A-15 | ☑ | Does Tank01 return **stat-level** projections (and usable odds/news) on Basic? | Secondary source is useless if it is points-only; Pro spend should wait on proof | Inspect live `getNFLProjections` before Pro | **2 Sep 2026:** Basic RapidAPI key returns nested Passing/Rushing/Receiving/Kicking and teamDefenseProjections. `week=season` ≈ 623 players; week 1 ≈ 513. Completions present (QB inflation). K is `fgMade`/`fgMissed`/`xpMade`/`xpMissed` (mapped to `fg`/`fga`/`pat_*`); no distance bands. DST has `ptsAgainst` but no `dst_yds_allowed`; `returnTD` is present but not folded into `dst_td` (unclear if additive vs subset of `defTD`). `getNFLNews?recentNews=true` and `getNFLBettingOdds` work; implied totals derived in client (D-87). |
| A-16 | ☐ | FantasyPros `consensus-rankings?type=ADP&position=ALL` returns a full board with `rank_ave` / `yahoo_id` | Player-pool ADP delta (D-88) fails loud if this payload is empty or missing identifiers | `python -m data player-pool` before draft; inspect one skill-position row | |
| A-17 | ☐ | Typed Yahoo draft-room names match the player-pool rows under a 1-minute clock | A miss or collision marks the wrong player drafted (or stalls on candidates). DST names are the likely miss | During a mock, type the Yahoo display name for a skill player, a suffix name (Jr/II), two Allens, and a DST | |
| A-18 | ☐ | Rehearsal-mode isolation: `--state-dir` never points at the real runtime root | A mock run in the live root pollutes `kb.db` and `notes/` before the draft starts | Run `python -m draft serve --state-dir <temp>` and confirm banner + writes land there; run the explicit rejection case against the real root | |
| A-19 | ☐ | Post-draft backup copy + name leak check | Draft-night attribution is unrecoverable state. A backup without a leak scan can still block publication later | Immediately after draft, copy `kb.db` and `notes/` off the machine that ran non-rehearsal; grep backup for real manager/team names | |
| A-20 | ☐ | No pre-draft council debate path for autopick sheet or `strategy.json` | Current plan logs per-pick council output but not "why this pre-rank order / strategy mode" before the room opens | Decide whether to add a pre-draft council run type this season or defer to post-season analysis | |

---

## B. Week 1 — behaviour that can only be observed live

| # | Status | Item | Why it matters | How to check | Resolution |
|---|---|---|---|---|---|
| B-1 | ☐ | "Lock Benched Players: No" — do benched players actually lock at their kickoff? | If they don't, late-window swaps have much more freedom and the lineup pass schedule should exploit it. Do not reason from the setting name | Watch an actual bench player after his game starts | |
| B-2 | ☐ | Yahoo's exact weekly waiver processing time | Monday-evening submission window is built on an assumption. If processing runs earlier, claims silently miss | Submit a low-stakes claim, watch when it resolves | |
| B-3 | ☐ | Inactive report timing vs. the Sunday 11:45 pass | Inactives are the highest-value input to the lineup. If the pass runs before they post, it's using stale information | Compare the pass timestamp against when inactives appeared | |
| B-4 | ☐ | Does the API expose the counterparty's `trade_note` on incoming offers? | The Negotiator needs to read their argument to respond to it. If not exposed, negotiation is one-directional | Wait for a real offer, or ask a league member to send one | |
| B-5 | ☐ | Is cancelling a proposed trade available via API, not just the web UI? | The offer-expiry design depends on programmatic withdrawal | Propose a low-stakes trade and cancel it via API | |
| B-6 | ☐ | Token refresh failure mode — what happens when Yahoo invalidates a refresh token? | Silent auth failure means nothing gets submitted and everything looks fine | Force an invalid token in a test run, confirm it alerts as P1 | |
| B-7 | ☐ | Push alerts actually arrive, on a locked phone, on a Sunday | The entire failure design assumes the alert reaches you. Untested alerting is no alerting | Fire a test P1 from the VPS before week 1 | |
| B-8 | ☐ | Dead-man switch fires when a run is skipped entirely | Ping-on-submission is the design; verify a run that submits nothing does NOT ping | Disable a timer deliberately, confirm the alert arrives | |
| B-9 | ☐ | Does the API expose live in-progress matchup scores mid-week? | Score-aware late passes depend on it. If scores only settle post-week, the Sunday-night and Monday passes lose their main input | Check a matchup endpoint during Sunday afternoon games | |
| B-10 | ☐ | Confirm a real Yahoo box score matches `fantasy_points` (leftover yards, kicker bands, DST tiers, signed penalties) | D-84 assumes leftover yards are discarded when fractional points are off. If Yahoo differs, projections and Tuesday attribution silently drift | Pick one completed week-1 game per position, compute from the stat line, compare to Yahoo's fantasy total | |

---

## C. Early season — first three weeks

| # | Status | Item | Why it matters | How to check | Resolution |
|---|---|---|---|---|---|
| C-1 | ☐ | Map the 28 Nov trade deadline to an NFL week number | The horizon curve keys off weeks-to-deadline. Roughly week 12, unverified | Check against the actual 2026 NFL schedule | |
| C-2 | ☐ | League reviews the private log site, approves or denies the public build | Weeks 1–3 run private by design. Per-run approval, per participant on trade threads | Share the private link after week 3 | |
| C-3 | ☐ | FantasyPros attribution present in the page footer | Required by their API licence for published work | Check the rendered public build | |
| C-4 | ☐ | Trade review window (2 days) overlapping the Tuesday waiver run | A player in a pending trade may not be rosterable when a claim processes | Watch the first trade that lands near a Tuesday | |
| C-5 | ☐ | Is `unanimous_override` actually firing, or is the GM rubber-stamping? | If the GM never overrides anyone, the council is theatre. Early signal on the whole premise | Query `decisions` after week 3 | |

---

## D. In-season, ongoing

| # | Status | Item | Why it matters | Cadence | Resolution |
|---|---|---|---|---|---|
| D-1 | ☐ | Trade spam monitoring | Flagged as the most likely thing needing mid-season correction. Cooldowns and caps are tunable in `strategy.json` | Weekly, via the trade monitor | |
| D-2 | ☐ | Scoring table diff alerts | A mid-season rule change that goes unnoticed silently invalidates every projection | Automatic — but confirm the alert path works | |
| D-3 | ☐ | Team count changes | Playoff race, veto threshold, waiver depth all derive from it | Automatic — confirm nothing is hardcoded | |
| D-4 | ☐ | Persona drift, especially Belichuk's brevity | Terseness is the hardest constraint to hold. Models drift toward explaining themselves | Read the log weekly. It's the point of the log | |
| D-5 | ☐ | Off-box backup of `kb.db` and `notes/` running | The only unrecoverable state in the system | Confirm the first backup actually restored | |
| D-6 | ☐ | UNS/MQTT: broker auth, tunnel WSS, engine publisher, console panels | Adopted in design (D-75–D-79, `uns.md`); build deferred past the draft | Three `milestone:season` issues seeded after the initial backlog | |

---

## E. Post-season

| # | Status | Item | Why it matters | Resolution |
|---|---|---|---|---|
| E-1 | ☐ | Decide whether to publish partner models | Private indefinitely by default. Accurate and unkind; requires a deliberate code change, not a checkbox | |
| E-2 | ☐ | Calibration analysis with sample sizes reported | The actual research output. Report N alongside every rate | |
| E-3 | ☐ | Archive the season — O-11 | | |
| E-4 | ☐ | Cancel FantasyPros and Tank01 subscriptions | Auto-renewing. Easy to forget and pay for a year of nothing | |
| E-5 | ☐ | Destroy the Vultr instance if not continuing | Stopped instances keep billing until destroyed | |

---

## F. Unresolved design questions

These are decisions, not verifications. Tracked in `architecture.md`
§10; listed here so there is one place to look.

| # | Status | Question |
|---|---|---|


| O-11 | ☐ | Season-end and archival — **deferred to December by decision**. Sub-questions: halt on elimination vs. play out week 17; whether next season inherits partner models and league lore; whether to publish the dataset alongside the writeup. No build dependency. |

Resolved: O-1 (§1), O-2 (§3), O-3 (§5), O-4 (§9.3), O-5 (§7.4),
O-6 (§3.1), O-7 (§7.3), O-8 (§7.2), O-9 (§7.4).

Remaining: O-11 (season-end archival).
