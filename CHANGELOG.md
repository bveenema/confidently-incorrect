# Changelog

## Unreleased

- Yahoo OAuth 2.0 client: one-time `oob` authorize, token persist on the
  state volume, unattended refresh, and a smoke read of own team,
  league settings, and roster (`python -m yahoo authorize|smoke`).
  Live verification is still blocked on Yahoo's Fantasy API access
  program (follow-up A-12).
