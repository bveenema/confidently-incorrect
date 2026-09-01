# Unified Namespace

Walker Reynolds' UNS pattern applied to this project: a semantic MQTT
topic tree is the current-state bus. `kb.db` remains the record.

This document is the namespace specification. Publishers and the admin
console must follow it. See architecture D-75–D-79.

## Hybrid model

| Store | Owns |
|---|---|
| MQTT UNS (retained messages) | What is true *now* — last run, last brief, roster, knobs, health |
| `kb.db` | What *happened* — briefs, considered options, attributions, deploys |
| Static log site | Rendered history; cannot consume MQTT |

The engine writes `kb.db` first, then publishes best-effort. A broker
outage must never lose ledger data or block a Yahoo submission (D-76).

## Enterprise root

```
confidently-incorrect/<season_id>/…
```

The team name is the enterprise root. `ci` is **not** a topic prefix —
it is the Podman image tag and the `/srv/ci/` volume path only.

`season_id` is the same identifier stamped on ledger rows (D-74), e.g.
`2026`.

## Hierarchy

ISA-95-style levels, adapted to a single-team front office:

```
confidently-incorrect/
  <season_id>/
    engine/
      runs/<decision_type>/status     lineup | waiver | trade | draft | attribution
    council/
      <persona>/brief                 belichuk | brand | taco | muskett | maddox | lasso
      gm/decision
    team/
      roster
      matchup
    league/
      scoring
      settings
    transactions/
      trades/<id>/state
      waivers/<id>/state
    ops/
      deploys
      config_changes
      alerts
      health
```

Personas and decision types are path segments, not payload fields that
a subscriber must parse to find the right stream.

## Retained-message policy

Publishers are ephemeral oneshot containers. They exit after each run.
Consumers (the admin console, a debug client) connect hours later.

**Every current-state topic is published retained.** Last-known-good
is load-bearing. Do not publish retained on a topic whose last message
is a transient event that should disappear — if we later need fire-and-
forget alerts, use a sibling `/events` path that is not retained.

## Payload conventions

- Encoding: UTF-8 JSON. Not Sparkplug B (D-79).
- Every payload includes `ts` as an ISO-8601 timestamp in
  `America/New_York`. Oneshot publishers cannot use MQTT LWT for
  liveness; a stale `ts` is how a consumer knows the data is old.
- Every payload includes `season_id`.
- Player keys, never real manager or team names. Pseudonymization
  happens at ingest, before any publish (same rule as `kb.db`).
- Numbers that are league scores are integers.

Minimal envelope:

```json
{
  "season_id": "2026",
  "ts": "2026-09-13T11:47:02-04:00",
  "run_id": "…",
  "payload": {}
}
```

## Example topics

| Topic | Retained | Who publishes | What it holds |
|---|---|---|---|
| `confidently-incorrect/2026/engine/runs/lineup/status` | yes | engine | last lineup pass: exit, slots decided, lock window |
| `confidently-incorrect/2026/council/belichuk/brief` | yes | engine | latest specialist brief (schema in council-prompts.md) |
| `confidently-incorrect/2026/council/gm/decision` | yes | engine | latest GM verdict |
| `confidently-incorrect/2026/team/roster` | yes | engine | current roster, slots, IR |
| `confidently-incorrect/2026/league/scoring` | yes | engine | live scoring table; diffs also land here |
| `confidently-incorrect/2026/transactions/trades/<id>/state` | yes | engine | pending / accepted / vetoed / expired |
| `confidently-incorrect/2026/ops/deploys` | yes | deploy.sh | last deploy SHA, whether decision logic was touched |
| `confidently-incorrect/2026/ops/config_changes` | yes | admin console API | last knob change (the POST still writes `config_changes`) |
| `confidently-incorrect/2026/ops/health` | yes | engine / timers | last successful run per timer |

## What does not go on the bus

- Historical aggregations (persona hit rates, calibration bands). Those
  stay SQL over `kb.db`.
- Real names, tokens, the pseudonym mapping.
- `notes/managers/` content.
- Yahoo write payloads. Guardrails sit between the GM and the API;
  the broker is not on that path.

## Broker (this repo)

Local: `eclipse-mosquitto:2` in `compose.yml`. Listeners bind
localhost — 1883 (MQTT) and 9001 (WebSockets). Anonymous is allowed
**only** on local compose. Persistence is `$CI_STATE_DIR/mosquitto`.

VPS auth, Quadlet, and the Cloudflare Tunnel WSS route are a
`milestone:season` issue. Do not copy `allow_anonymous true` onto
the box.
