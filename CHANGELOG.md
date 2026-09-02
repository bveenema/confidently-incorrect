# Changelog

## Unreleased

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
