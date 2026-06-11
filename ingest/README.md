# mundial — World Cup 2026 data capture

Step 1 of an AI-powered Discord app for the FIFA World Cup 2026: capture the
tournament data (teams, groups, stadiums, the 104-match schedule with kickoff
times + venues, and the knockout bracket) into PostgreSQL. No app/bot yet.

Data comes from a vendored snapshot of
[`rezarahiminia/worldcup2026`](https://github.com/rezarahiminia/worldcup2026)
(see `ingest/data/worldcup2026/SOURCE.md`). Farsi columns are dropped; broken flag
URLs are kept as-is for a later fix. Players are out of scope — the `players`
table exists but is intentionally empty (reserved for a later API-Football ingest).

## Layout

```
mundial/
├── docker-compose.yml      # one-shot `ingest` service on dbnet; no postgres service
├── .env.example            # POSTGRES_* connection vars (no password)
├── scripts/setup_db.sh     # create mundial db/role/schema on shared postgres, then ingest
└── ingest/                 # SQLAlchemy models + Alembic migration + seed + vendored data
```

## Prerequisites

- The shared PostgreSQL container (`postgres`) running on the external `dbnet`
  network (from `/home/iktdts/apps/infra/postgresdb`).
- The `intranet` and `dbnet` Docker networks created
  (`/home/iktdts/apps/infra/networks/setup_networks.sh`).

## Run

```bash
cd /home/iktdts/apps/website/mundial

# 1. Provide the DB password (same value the shared postgres superuser can set).
mkdir -p secrets && printf '%s' 'YOUR_PASSWORD' > secrets/db_password.txt && chmod 600 secrets/db_password.txt

# 2. Create the mundial db/role/schema and run migrations + seed in one shot.
bash scripts/setup_db.sh
```

To re-run just the migration + seed (idempotent):

```bash
docker compose run --rm ingest
```

## Verify

```bash
docker exec -it postgres psql -U mundial -d mundial -c "
SELECT (SELECT count(*) FROM teams)            AS teams,
       (SELECT count(*) FROM stadiums)         AS stadiums,
       (SELECT count(*) FROM group_standings)  AS standings,
       (SELECT count(*) FROM matches)          AS matches,
       (SELECT count(*) FROM players)          AS players;"
# expect: teams=48, stadiums=16, standings=48, matches=104, players=0
```

Bracket check (knockout slots carry labels until teams are decided):

```sql
SELECT id, "group", type, home_team_label, away_team_label
FROM matches WHERE home_team_label IS NOT NULL ORDER BY id LIMIT 5;
```
