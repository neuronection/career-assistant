"""Mode dispatcher: `python -m careerassistant [app|web|seed|backup|restore]`.

app (default) — pywebview desktop window over a local loopback server,
                with tray + background mode (`app --tray` boots tray-only
                for login auto-start).
web           — fixed loopback port + system browser (no window shell).
seed          — apply migrations + idempotent starter catalog, then exit.
backup        — create a backup archive now, then prune old ones.
restore ZIPO  — replace local data (db/uploads/secret) from an archive; the
                second argument must be the path to the backup zip.

All modes bootstrap the local profile first: platform data dir, SQLite
database, uploads directory and a generated JWT secret (data_dir/secret.key).
"""

import sys

USAGE = (
    "usage: python -m careerassistant [app|web|seed|backup|restore ZIP]\n"
    "       python -m careerassistant app --tray   (background auto-start)\n"
    "restore replaces local data and cannot be undone."
)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    mode = args[0] if args else "app"
    if mode in ("-h", "--help"):
        print(USAGE)
        return 0
    if mode not in ("app", "web", "seed", "backup", "restore"):
        print(USAGE, file=sys.stderr)
        return 2
    tray_only = False
    if mode == "app" and "--tray" in args:
        args.remove("--tray")
        tray_only = True

    from pathlib import Path

    from app.local import (
        bootstrap_environment,
        default_data_dir,
        run_migrations,
        seed_catalog_data,
    )

    data_dir = default_data_dir()
    bootstrap_environment(data_dir)
    if mode == "app":
        # Desktop modes declare their channel capability before Settings
        # is imported (plan 36 desktop scenario / plan 25 flag pattern).
        import os

        os.environ["DESKTOP_MODE"] = "1"

    if mode == "restore":
        if len(args) != 2:
            print(USAGE, file=sys.stderr)
            return 2
        from app import backups

        archive = Path(args[1])
        if not archive.is_file():
            print(f"No such archive: {archive}", file=sys.stderr)
            return 1
        summary = backups.restore_backup(data_dir, archive)
        print(f"Restored from {archive.name}: {summary}")
        return 0

    # Corrupt-DB guard must run before anything opens the database.
    from app import backups

    state = backups.verify_or_repair_database(data_dir)
    if state != "ok":
        print(f"Database recovery: {state}", file=sys.stderr)

    if mode == "backup":
        run_migrations()
        try:
            archive = backups.create_backup(data_dir)
        except RuntimeError as exc:
            print(f"Backup failed: {exc}", file=sys.stderr)
            return 1
        removed = backups.prune_backups(data_dir)
        print(f"Backup: {archive.name} (pruned {removed})")
        return 0

    run_migrations()
    seed_catalog_data()

    archive = backups.backup_if_due(data_dir)
    if archive is not None:
        print(f"Scheduled backup: {archive.name}")

    if mode == "seed":
        return 0

    from app import shell

    if mode == "app":
        shell.run(tray_only=tray_only)
    else:
        shell.run_browser()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
