# Off-host backup timer (T1)

The compose `backup` sidecar is a **same-host** dump loop (non-DR). For a T1
deployment, schedule `scripts/backup.sh` on the host so the archive leaves the
machine:

```ini
# /etc/systemd/system/career-backup.service
[Unit]
Description=Career Assistant off-host backup
[Service]
Type=oneshot
WorkingDirectory=/srv/career-assistant
EnvironmentFile=/srv/career-assistant/docker/.env
ExecStart=/srv/career-assistant/scripts/backup.sh
```

```ini
# /etc/systemd/system/career-backup.timer
[Unit]
Description=Daily Career Assistant backup
[Timer]
OnCalendar=*-*-* 03:15:00
Persistent=true
[Install]
WantedBy=timers.target
```

Install `awscli`, `rclone` or `azcopy` (whichever `BACKUP_REMOTE` uses) on the
host, set `BACKUP_REMOTE` (and `BACKUP_AGE_RECIPIENT` when encryption is
required), then `systemctl enable --now career-backup.timer`. Alert when the
newest `backup_runs` row is older than 2× the interval.
