# Backup, restore & migration — Career Assistant (self-host)

Conforms to the family backup-migration doc template.
Cross-VM mechanics live in the canonical runbook:
[`neuronection/self-host` → docs/migration.md](https://github.com/neuronection/self-host/blob/main/docs/migration.md).

## What one backup contains

`bash scripts/backup.sh [output-dir]` produces
`backups/career-assistant-<timestamp>.tar.gz`:

- `database.dump` — `pg_dump` custom format of `neuronection_career`
- `uploads.tar.gz` — the uploads volume (documents)
- `manifest.json` — contents + versions (ledger row in `backup_runs.jsonl`)

Archives never contain secrets; `docker/.env` is excluded on purpose.

## Off-host targets (set in `docker/.env` or the shell)

| Key | Target |
|---|---|
| `BACKUP_REMOTE` | `s3://bucket/prefix` (aws s3 / rclone), `https://acct.blob…/ctr` (azcopy), or any `remote:path` rclone target |
| `BACKUP_AGE_RECIPIENT` | age public key — archive is encrypted before upload |

A local-only backup is non-DR: label it as such and add an off-host
target. Schedule with cron (the backup-timer feature can drive it) —
nightly is a sane default.

## Restore

```bash
bash scripts/restore.sh <archive.tar.gz>   # replaces DB + uploads volume
```

Destructive by design (the archive **is** the state). Encrypted
archives (`.tar.gz.age`) decrypt first with the local age identity
(`AGE_IDENTITY`, default `~/.config/age/keys.txt`) — the private key
lives with the operator, never on the producing server.

## The data-key rule

`CAREER_DATA_KEY` in `docker/.env` encrypts columns at rest. It is
**not** in the archive — when moving to another VM, copy `docker/.env`
(0600) to the new install **before** restoring, then fix
host-specific values (`CAREER_PUBLIC_URL`, ports). Full runbook:
[self-host migration guide](https://github.com/neuronection/self-host/blob/main/docs/migration.md).

## Restore drill

Once a month (and after any version change): restore the latest archive
into a scratch install (`--env-only` + old `.env` + `restore.sh`), log
in, open one real entity, then delete the scratch. If the drill
fails, the backup is not a backup.
