# Changelog

## Unreleased

- Player pool: merge FantasyPros and Tank01 season-long stat lines
  under league scoring, rank, build positional tiers, and compute
  ADP delta (`python -m data player-pool`). Incomplete K/DST lines
  are flagged and kept out of overall rank (D-88 / A-13).
- Tank01 client: `$CI_STATE_DIR/tokens/tank01.json`, mapped nested
  projection stat lines (not provider point totals), season and weekly
  pulls, injuries, news, and implied team totals from betting lines
  (`python -m data tank01-smoke`). Live Basic-tier check recorded as
  A-15 / D-87.
- Record D-85: the 6 Sep draft proceeds without live Yahoo API access
  (manual settings and picks). A-12 stays open for the season path.
- FantasyPros smoke treats truncation as fewer rows than `count`. HOF
  still sends `public_api_limited=true`; that flag is not a page cap
  (A-14).
- FantasyPros client: `$CI_STATE_DIR/tokens/fantasypros.json`, mapped
  stat lines (not provider point totals), weekly and week-0 projections,
  consensus `rank_std`, injuries, news, and `data.ATTRIBUTION`
  (`python -m data fantasypros-smoke`). Smoke fails if the pool is
  truncated or empty (D-86 / A-2).
- Scoring engine: `data.fantasy_points` turns a raw stat line into
  league points from the ingested table (D-84 / D-48). Leftover yards
  are discarded when fractional points are off; DST bands snap
  projections onto integer tiers. Provider point totals are ignored.
  A-6 still open — signed penalties apply as written.
- Draft-path league settings loader: `$CI_STATE_DIR/league-settings.json`
  (schema + fake template, `python -m data validate-league-settings`).
  Missing or invalid files fail loudly; no hardcoded team count,
  roster, or scoring (D-83). Live Yahoo pull and per-run diff stay
  with D-47 / A-12.
- Yahoo OAuth 2.0 client: one-time `oob` authorize, token persist on the
  state volume, unattended refresh, and a smoke read of own team,
  league settings, and roster (`python -m yahoo authorize|smoke`).
  Live verification is still blocked on Yahoo's Fantasy API access
  program (follow-up A-12).
