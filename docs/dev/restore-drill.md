# Restore drill — Career Assistant (server deployment)

Backup policy: restore is a **tested procedure**, not a script that fires and
hopes. Run this drill at least once per deployment shape (and after any
compose/credential change) before you ever need it. Goal: prove a backup
archive restores into a **throwaway** target, the app role is usable again,
and a known record is readable — all without touching the live database.

Applies to the Docker server stack (prod / standalone). The desktop profile
restores via `python -m careerassistant restore <zip>` and needs no drill
beyond running it once.

## 0. What you need

- A recent archive from `scripts/backup.sh`
  (`backups/career-assistant-YYYYMMDD-HHMMSS.tar.gz` — DB dump + uploads +
  manifest), ideally one uploaded off-host (`BACKUP_REMOTE`), restored from
  the object store first: a restore drill that only reads the local disk
  does not test the off-host leg.
- The deployment secrets (`docker/.env`): `POSTGRES_PASSWORD`
  (owner/bootstrap), `CAREER_DB_OWNER_PASSWORD`, `CAREER_DB_PASSWORD`.
- A **known record** to verify: one real row the operator can name (e.g.
  the admin user's email in `users`, or a specific `job_postings` row).

## 1. Restore into a throwaway target first

Never restore into the live database. Create a scratch database next to the
running stack and restore there:

```bash
cd career-assistant
# 1a. scratch DB on the same Postgres container (owner connection)
docker compose -f docker/docker-compose.prod.yml exec db \
  env PGPASSWORD="$CAREER_DB_OWNER_PASSWORD" \
  psql -U "${POSTGRES_USER:-neuronection_career_owner}" \
  -d "${POSTGRES_DB:-neuronection_career}" \
  -c "CREATE DATABASE career_restore_check;"

# 1b. unpack the archive and restore into the scratch DB only
tar xzf backups/career-assistant-*.tar.gz -C /tmp/restore-check
docker compose -f docker/docker-compose.prod.yml exec -T db \
  env PGPASSWORD="$CAREER_DB_OWNER_PASSWORD" \
  pg_restore -U "${POSTGRES_USER:-neuronection_career_owner}" \
  -d career_restore_check --if-exists --no-owner < /tmp/restore-check/database.dump
```

`--no-owner` matters: inside the dump every object belongs to the owner
role; the scratch restore keeps it that way and never reassigns anything.

## 2. Re-grant the app role (the step that bites)

A restored database carries the **grants of the moment it was dumped**.
After a restore — and always before pointing the app at it — re-run the
provisioning seam so the DML-only app role and default privileges are
re-established, then let migrate verify them:

```bash
docker compose -f docker/docker-compose.prod.yml run --rm migrate
```

`migrate` (credential policy) creates/verifies the app role, re-grants DML on all
tables and sequences, sets `ALTER DEFAULT PRIVILEGES`, and **verifies**:
it fails loudly if the app role can read what it must, or holds `CREATE`
(schema DDL) it must not.

## 3. Verify named counts and a known record

```bash
docker compose -f docker/docker-compose.prod.yml exec db \
  env PGPASSWORD="$CAREER_DB_OWNER_PASSWORD" \
  psql -U "${POSTGRES_USER:-neuronection_career_owner}" -d career_restore_check -c "
  SELECT count(*) AS users FROM users;
  SELECT count(*) AS postings FROM job_postings;
  SELECT email FROM users ORDER BY created_at LIMIT 1;   -- your known record
"
```

Compare counts against the live system (or the manifest's expectations).
Then boot a **throwaway app** against the scratch DB, never the live one:

```bash
docker run --rm --network career-assistant_default \
  -e CAREER_APP_ENV=production \
  -e CAREER_DATABASE_URL="postgresql+asyncpg://${CAREER_DB_APP_USER:-neuronection_career_app}:${CAREER_DB_PASSWORD}@db:5432/career_restore_check" \
  -e CAREER_DB_SPLIT=1 \
  -e CAREER_SESSION_KEY="$CAREER_SESSION_KEY" \
  -e CAREER_REFRESH_KEY="$CAREER_REFRESH_KEY" \
  -e CAREER_DATA_KEY="$CAREER_DATA_KEY" \
  "${CAREER_IMAGE:-career-assistant:local}" \
  sh -c 'cd /app/backend && python -m careerassistant preflight'
```

`preflight` reading the scratch DB through the **app role** is the app-level
proof: schema present, at this release's chain, readable with app
privileges.

## 4. Ledger check (did the backups themselves run?)

```bash
docker compose -f docker/docker-compose.prod.yml exec db \
  env PGPASSWORD="$CAREER_DB_OWNER_PASSWORD" \
  psql -U "${POSTGRES_USER:-neuronection_career_owner}" \
  -d "${POSTGRES_DB:-neuronection_career}" \
  -c "SELECT started_at, status, bytes, destination, error_class
      FROM backup_runs ORDER BY started_at DESC LIMIT 5;"
```

A row older than 2× the backup interval (or `status='failed'`) means the
backup chain is broken — fix it before archiving this drill.

## 5. Switchover (only when this was a real restore)

1. Stop the app (`docker compose stop app`);
2. restore the real target from the same archive (steps 1–2 against
   `${POSTGRES_DB}`, with the app stopped);
3. re-grant (step 2 — mandatory);
4. start the app and watch readiness:
   `curl -fsS http://127.0.0.1:8100/ready` must return 200 (the `/ready`
   hard check includes **DB at Alembic head**) before opening the proxy;
5. keep the previous (broken) target for rollback until verified;
6. drop the scratch DB: `DROP DATABASE career_restore_check;`.

## Pass criteria (record the run)

- [ ] Archive restored into a **throwaway** target only;
- [ ] `migrate` re-grant + verification exited 0 (app role DML-only, can read);
- [ ] named row counts match; the known record reads back;
- [ ] `/ready` = 200 on the restored target (app role);
- [ ] `backup_runs` ledger shows recent `ok` rows, off-host destination set;
- [ ] operator + date recorded (the owner runs and records the drill).
