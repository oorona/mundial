# Setup

## First-time setup (run once after cloning)

1. Generate secrets (encryption key + Postgres superuser password)
   ```bash
   ./setup_secrets.sh
   ```
   The script will prompt for the Postgres superuser password. Set it to whatever you want — it just needs to match `POSTGRES_PASSWORD` in `docker-compose.yml`.

2. Start the database container
   ```bash
   docker compose up -d postgres
   ```
   > The Postgres server runs as a Docker service named `postgres`. This is also the hostname you will enter in the Setup Wizard — not `localhost`.

3. Create the app database user and schema
   ```bash
   ./setup_database.sh --container postgres --user <yourbot> --db <yourbot>
   ```
   - `--container postgres` is the Docker service name running Postgres (matches `docker-compose.yml`)
   - `--user` and `--db` are the app credentials you are creating — use the same value for both unless you have a reason not to
   - The script will prompt for a password. Note the user, password, and db name — you will enter them in the Setup Wizard in step 6.

4. Write-protect core files and clean demo plugins
   ```bash
   chmod +x init.sh && ./init.sh
   ```
   This removes all demo plugin folders from `plugins/` and write-protects core framework files. The blank `plugins/_template/` is kept as a starting point.

5. Start the full stack
   ```bash
   docker compose up
   ```

6. Open the app in your browser — you will be redirected to the Setup Wizard.
   Enter your Discord token and the database credentials from step 3:
   - **Host:** `postgres` (the Docker service name, not localhost)
   - **Port:** `5432`
   - **User / Password / Database:** what you chose in step 3

   Credentials are saved encrypted. The wizard never runs again after this.

---

## Building features

All new code goes into a staging folder, never directly into the live project.

1. Copy the plugin template
   ```bash
   cp -r plugins/_template plugins/<your_feature>
   ```

2. Build your feature inside `plugins/<your_feature>/`
   (cog, API router, frontend page, translations — see `docs/integration/08-plugin-workflow.md`)

3. Validate and install
   ```bash
   ./install_plugin.sh <your_feature>
   ```
   Add `--dry-run` to preview changes without writing any files.
   Add `--force` to skip validation (not recommended).

5. If the plugin added database tables, run migrations
   ```bash
   docker compose exec backend alembic upgrade head
   ```

6. Restart the bot and frontend to pick up the changes
   ```bash
   docker compose restart bot frontend
   ```

---

## Reference

- `CLAUDE.md` — rules every developer and AI assistant must follow
- `docs/DEVELOPER_MANUAL.md` — full architecture and extension guide
- `docs/integration/08-plugin-workflow.md` — detailed plugin workflow
