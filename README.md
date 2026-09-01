# Mundial

A World Cup 2026 prediction league (quiniela) for Discord communities, built as plugins on the Baseline bot platform. Members predict every match score, an AI worker confirms real-world results from the web and re-scores the table live, an AI "machine player" competes in the league, and the whole tournament — groups, bracket, venues — is explorable as a Discord Activity and on the web dashboard.

## The plugins

- **predictions** — the quiniela core: per-match score predictions with phase/kickoff locking and configurable Kicktipp-style scoring (participation floor + exact/diff/tendency weights; knockout rounds score the same as group rounds). Guild-scoped with RLS.
- **live_tracker** — an AI worker that searches the web for live scores, confirms finished results, recalculates standings and the bracket, re-scores predictions, and streams match events to a Discord channel; admins can correct results. Knockout finals aren't committed level without decisive penalties.
- **ai_player** — a machine contestant: predicts each upcoming match using AI with Google-grounded search (internet consensus), gets scored like everyone else, and appears in the leaderboard.
- **leaderboard** — per-server standings as a live SSE table on the web plus a single self-updating Discord message.
- **goal_clips** — ingests goal video clips from a companion Fox browser extension and pairs each with a stream-confirmed goal, so the tracker posts the actual goal footage instead of a gif.
- **worldcup_data** — the World Cup 2026 data layer (teams, groups, standings, matches, players, bracket) behind the `/mundial` command and the exploration pages.
- **fixtures_activity** — an embedded Discord Activity: group navigation, team and match views, the knockout bracket, venues, and a host-city map — reusable inside the web dashboard.

## Under the hood

Built on the Baseline platform (see [docs/BASELINE_FRAMEWORK.md](docs/BASELINE_FRAMEWORK.md)): auto-sharded discord.py bot + FastAPI backend + Next.js 16 dashboard with six permission levels, RLS-scoped guild data, encrypted settings wizard, audit logging, multi-provider LLM service, and the plugin installer/validator. Both scoring engines (backend and bot) are held to parity by a shared canonical point table in the test suites.

## Tech stack

FastAPI + PostgreSQL + Redis · discord.py · Next.js 16 + TypeScript · Docker Compose behind Traefik · Gemini/OpenAI via the platform LLM service with per-guild spend caps.

Setup: [SETUP.md](SETUP.md) · Tests: `./test.sh` (needs the docker stack).
