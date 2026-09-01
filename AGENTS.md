# AGENTS.md

Binding project rules live in [`.ai/rules.md`](.ai/rules.md). Read that
file before any non-trivial change. Do not copy those rules here — one
source of truth.

Hephaestus workflow specs live alongside them in `.ai/workflows/` and
`.ai/agents/`. Do not merge the two. Cursor adapters are in
`.cursor/commands/` and `.cursor/agents/`. Vendored from
[amurshak/hephaestus](https://github.com/amurshak/hephaestus) at
`a121813a12f975ec710ef527e15e7627a10bdeb2` (v2.2.0), MIT — see
`.ai/HEPHAESTUS-LICENSE`.

Quality gates `/ship` reads are in `CLAUDE.md` under
`## Development Commands`.
