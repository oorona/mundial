# Data provenance — FIFA World Cup 2026

Snapshot of the dataset from:

- **Upstream repo:** https://github.com/rezarahiminia/worldcup2026
- **Branch:** `main`
- **Commit SHA:** `b632809e5a472485555449bbc08a20eaf00d33c0`
- **Snapshot date:** 2026-06-06

## Files (renamed from upstream)

| Local file       | Upstream file                  | Records |
|------------------|--------------------------------|---------|
| `teams.json`     | `football.teams.json`          | 48      |
| `groups.json`    | `football.matchtables.json`    | 12      |
| `stadiums.json`  | `football.stadiums.json`       | 16      |
| `matches.json`   | `football.matches.json`        | 104     |

These are MongoDB-style exports (each record carries a `_id.$oid`). We treat them
as a controlled, vendored snapshot so seeding runs offline and the data can be
hand-corrected (e.g. the broken flag URLs) without depending on the upstream repo
at runtime. To refresh, re-download the four files above from the pinned commit.

## Players (squad rosters)

`players.json` (1247 records) is parsed from a saved copy of the API-FOOTBALL
lineups page (the live page is behind a Cloudflare bot challenge, so the HTML was
downloaded in a browser):

- **Source page:** https://www.api-football.com/news/post/fifa-world-cup-2026-lineups-all-teams-coaches-and-players
- **Saved file:** `FIFA World Cup 2026 Lineups_ All Teams, Coaches and Players - API-FOOTBALL.html` (repo root)
- **Snapshot date:** 2026-06-06
- **Fields:** `team_id` (FK to our teams), `name`, `position`
  (Goalkeeper/Defender/Midfielder/Forward). 48 squads; ~26 players each.
- **Not present on the page:** coach names (title says "coaches" but the body lists
  only players) and player photos — so `players.photo`/`external_id` stay NULL,
  reserved for a later enrichment pass.

Country names were mapped to our team ids (aliases: Czechia→Czech Republic,
USA→United States, "Bosnia & Herzegovina"→"Bosnia and Herzegovina",
"DR Congo"→"Democratic Republic of the Congo").

## Team stats

`team_stats.json` (48 rows) holds per-team metadata used to UPDATE the `teams`
rows (the base team data comes from the repo above):

- **Source:** English Wikipedia national-team infoboxes (one per team), snapshot
  2026-06-06. FIFA ranking via the `{{FIFA World Rankings|CODE}}` template
  (dated 1 April 2026).
- **Fields:** `coach`, `nickname`, `confederation` (UEFA/CONMEBOL/CONCACAF/CAF/
  AFC/OFC), `wc_appearances` (count incl. 2026), `wc_first_year`, `wc_best_result`
  (e.g. "Champions (1958, 1962, …)", "Round of 16 (…)", "TBD" for debutants),
  `fifa_ranking` (a snapshot — it changes over time), `wikipedia_url` (canonical
  English Wikipedia article URL, redirects resolved — e.g. South Africa →
  "…national soccer team", DR Congo → "DR Congo national football team").
- **Title mapping notes:** USA/Canada/Australia use "… men's national soccer team";
  Sweden's plain title is a disambig → "Sweden men's national football team". A few
  values were cleaned of wiki templates (`{{nowrap}}`/`{{Plainlist}}`/`{{ubl}}`):
  Curaçao confederation, Ecuador/Iran/Belgium nicknames.

## Intentional exclusions

- **Farsi columns are dropped** at seed time and never stored: `name_fa` (teams,
  stadiums), `city_fa`, `country_fa` (stadiums), `persian_date` (matches).
- **Scorers** (`home_scorers`, `away_scorers`) are ignored — not needed yet.

## Flags (localized)

The upstream `flag` field held `flagcdn.com` URLs. All 48 were verified to resolve,
then downloaded locally for quality, consistency, and offline use:

- **Source:** `https://flagcdn.com/w640/{code}.png` (the upstream codes were already
  correct, incl. `gb-eng` / `gb-sct` for England / Scotland).
- **Stored in:** `../flags/{code}.png` — all PNG, consistent **640px width**
  (height varies by each flag's native aspect ratio; the app sizes the display box).
- **`teams.json` `flag` field** now holds the repo-relative path `flags/{code}.png`
  (not a URL), so re-seeding reproduces local paths. The app serves these files.

To re-download: re-run the w640 fetch for each team code into `../flags/`.

## How the knockout bracket is encoded

Knockout matches (`type` in `r32/r16/qf/sf/third/final`) have
`home_team_id`/`away_team_id` set to `"0"` (unresolved) and instead carry
`home_team_label`/`away_team_label` describing the slot, e.g.
`"Runner-up Group A"`, `"Winner Group E"`, `"3rd Group A/B/C/D/F"`,
`"Winner Match 99"`, `"Loser Match 101"`. The seed stores these labels and leaves
the team FKs NULL until results are known.
