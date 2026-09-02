# AI agent rules — Confidently Incorrect

These rules govern any AI agent (Cursor, Claude Code, or otherwise)
doing implementation work on this project. They are binding. Where a
rule conflicts with a request in chat, raise the conflict rather than
silently choosing.

---

## 1. Read before writing

Before any non-trivial change, read in this order:

1. `architecture.md` — what was decided and why. The decision log (D-1
   onward) is the authoritative record.
2. `implementation.md` — build order, critical path, league facts.
3. `followups.md` — what is unverified. Do not build on an assumption
   listed here as open without flagging it.
4. `council-prompts.md` — persona prompts and the brief schema.

If a request contradicts a recorded decision, **stop and say so**. Do
not implement the contradiction and do not quietly follow the old
decision either.

---

## 2. Documentation is load-bearing

The docs are not a description of the code. They are the specification,
and this project's whole premise is that its reasoning is auditable.

- Any change that alters or supersedes a recorded decision **must add a
  new numbered entry to the decision log** in `architecture.md`. Never
  edit an old entry to match new behaviour — supersede it.
- Any change that resolves an open item in `followups.md` **writes the
  answer into the Resolution column**. Never delete a row.
- Any new unknown discovered during implementation **gets added to
  `followups.md`** with its consequence stated, not just a TODO comment.
- Never restructure, reformat, or "tidy" these documents. Append and
  amend in place.

---

## 3. Mid-season change control

Once week 1 begins, code changes are confounds for the attribution data
(`architecture.md` §7.2). Treat them accordingly.

- **Every deploy after week 1 writes a row to the `deploys` table** in
  `kb.db`: timestamp, commit SHA, one-line description, and whether it
  touches decision logic. Attribution queries join against this.
- **Persona prompts are frozen for the season.** The characters do not
  change. If a prompt genuinely must change (a persona is producing
  unparseable output), record it as a deploy touching decision logic
  and note it in the log site, because every persona statistic before
  and after that point is measuring a different thing.
- **No deploys during game windows.** Thursday 17:00 ET through Monday
  23:59 ET is frozen except for a P1 fix. The cost of a bad deploy in
  that window is a missed lock.
- Tuesday and Wednesday are the change window.

### 3.1 Deploy discipline

- **Run `deploy.sh`. Do not improvise deployment commands over SSH.**
  The script enforces the freeze window, tags the image, records the
  deploy, and runs a dry-run check. Bypassing it skips all four.
- **Never hand-edit files on the VPS.** Anything changed directly on
  the box is config drift: it is not in the repo, it will not survive
  the next deploy, and nobody will remember it exists. Change it in a
  PR and deploy.
- **Never touch `/srv/ci/`** — `strategy.json`, `kb.db`, `notes/`, and
  the token file. That directory is runtime state, deliberately outside
  the git working directory. No git command should ever reach it.
- **Rollback retags a previous image; it does not rebuild.** The last
  five SHA-tagged images are kept for this reason.
- **Secrets are set on the box once, manually.** Never in the repo,
  never in an image layer, never regenerated or rotated by an agent
  without being asked.
- Infrastructure changes go through the same PR and documentation flow
  as application code.

---

## 4. Things that must never be done

These are not preferences.

- **Never hardcode a league-derived value.** Team count, scoring table,
  roster slots, playoff structure, trade deadline, waiver rules — all
  are read at runtime. Until A-12 unblocks D-47, the source is
  `$CI_STATE_DIR/league-settings.json` (D-83). After that, the Yahoo
  API. The league is expected to grow and settings can change
  mid-season. A constant here is a silent bug.
- **Never let model output reach the Yahoo API unvalidated.** Guardrails
  are deterministic code between the GM decision and execution. A
  guardrail implemented as a prompt instruction is not a guardrail.
- **Never add a deterministic quality floor to trade acceptance.** Being
  out-argued by a human is a protected feature. Validity checks only.
- **Never skip the `considered_options` snapshot.** It is written before
  execution, every run. Counterfactual data is unrecoverable afterwards.
  Do not optimize it away because it looks redundant.
- **Never let real manager or team names enter `kb.db`, `notes/`, logs,
  or any model prompt.** Pseudonymization happens at ingest, in the
  Yahoo client. The mapping table lives outside both stores.
- **Never include `notes/managers/` in a site build**, private or
  public. Exclusion is unconditional in the generator.
- **Never commit secrets.** Yahoo tokens, OpenRouter keys, and the
  pseudonym mapping are podman secrets or volume-mounted files. Not env
  files in the image, not in the repo, not in test fixtures.
- **Never swallow an exception on a write path.** A run that fails must
  exit non-zero and write a failed-run row. Silent success is the
  failure mode this system is most vulnerable to.
- **Never ping the dead-man switch on process start.** Only after a
  confirmed successful submission.

---

## 5. Correctness details that bite

- **Timezone is `America/New_York`** everywhere — the NFL schedule is
  ET. Never rely on the host's local time.
- **Scoring is integer.** Round projections; fractional points are off
  in this league.
- **Compute fantasy points from stat lines** using the league scoring
  table. Never consume a data provider's precomputed point total.
- **Retries are bounded by the lock window**, not by a fixed count.
- **Never retry a submission that may have partially succeeded.** Read
  roster state back and reconcile first.
- **A missing specialist brief does not block a run.** Record which
  persona was absent and proceed. A missing GM decision does block.

---

## 6. Testing

- Any change to the lineup, waiver, or trade submission path must be
  exercised in **dry-run mode** — full pipeline, no write to Yahoo —
  before it is deployed.
- Dry-run mode is a first-class feature, not a debug flag. It stays
  working.
- Do not claim something works because it compiles or because the code
  looks right. Say what was actually run and what the output was.

---

## 7. Working style

- Prefer the smallest change that solves the problem. This is a
  single-user seasonal project, not a platform.
- Do not add abstraction layers, plugin systems, or configuration for
  things that have exactly one value.
- Do not add dependencies without saying why in the commit message.
- If a task turns out to be larger than described, stop and report
  rather than expanding scope silently.
- Ask when a decision is genuinely ambiguous. Guessing and documenting
  the guess is worse than asking, because the guess enters the record
  as though it were reasoned.

---

## 8. Before finishing any task

- [ ] Does this contradict a decision in `architecture.md`? If yes, was
      a new decision logged?
- [ ] Did this surface a new unknown? If yes, is it in `followups.md`
      with its consequence?
- [ ] Does this touch decision logic mid-season? If yes, will the deploy
      be recorded?
- [ ] Are any league-derived values hardcoded?
- [ ] Could any real name reach the ledger, notes, or a prompt?
- [ ] Was it actually run, or does it just look correct?
