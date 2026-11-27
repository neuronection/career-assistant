"""Mode dispatcher:
`python -m careerassistant [app|web|seed|backup|restore|enginecheck|preflight|migrate]`.

app (default) — pywebview desktop window over a local loopback server,
                with tray + background mode (`app --tray` boots tray-only
                for login auto-start).
web           — fixed loopback port + system browser (no window shell).
seed          — apply migrations + idempotent reference banks (no catalog), then exit.
backup        — create a backup archive now, then prune old ones.
restore ZIPO  — replace local data (db/uploads/secret) from an archive; the
                second argument must be the path to the backup zip.
enginecheck   — print one PDF through the engine and report page-count
                health; exit 0/1 (no database, no window).
preflight     — check that the configured datastore matches this release's
                schema chain; exit 0/1 (no bootstrap, no window). Server
                entrypoints run this before serving.
migrate       — SERVER one-shot provisioning (ADR-0062 §3 / ADR-0064):
                app role + grants, extensions, Alembic, checkpoint schema,
                vector spaces, re-grant — as the owner role, then exit.
                `serve` never runs migrations; desktop migrates locally
                at boot as before. Refuses the SQLite profile.

All modes except enginecheck, preflight and migrate bootstrap the local
profile first: platform data dir, SQLite database, uploads directory, then
the datastore break guard (a pre-v0.17 datastore is moved aside, never
deleted) and migrations.
"""

import sys
from pathlib import Path

USAGE = (
    "usage: python -m careerassistant [app|web|seed|backup|restore ZIP|migrate]\n"
    "       python -m careerassistant app --tray   (background auto-start)\n"
    "       python -m careerassistant enginecheck  (PDF engine health probe)\n"
    "       python -m careerassistant preflight    (datastore schema check)\n"
    "       python -m careerassistant migrate      (server one-shot provisioning)\n"
    "restore replaces local data and cannot be undone."
)


def _report_startup_error(data_dir: Path, error: Exception) -> None:
    """Surface a refusing boot where a window would otherwise show nothing."""
    error_path = data_dir / "STARTUP-ERROR.txt"
    try:
        error_path.write_text(str(error) + "\n", encoding="utf-8")
        written = True
    except OSError:
        written = False
    sys.stderr.write(f"\n{error}\n")
    if written:
        sys.stderr.write(f"\nThis message was written to {error_path}\n")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    mode = args[0] if args else "app"
    if mode in ("-h", "--help"):
        print(USAGE)
        return 0
    modes = ("app", "web", "seed", "backup", "restore", "enginecheck", "preflight", "migrate")
    if mode not in modes:
        print(USAGE, file=sys.stderr)
        return 2
    tray_only = False
    if mode == "app" and "--tray" in args:
        args.remove("--tray")
        tray_only = True

    if mode == "enginecheck":
        import asyncio

        from app.services.cv.cv_pdf_service import engine_check

        ok, detail = asyncio.run(engine_check())
        print(("ok: " if ok else "fail: ") + detail)
        return 0 if ok else 1

    if mode == "preflight":
        from app.core.config import settings
        from app.local import DatabaseVersionError
        from app.storage.datastore_guard import assert_compatible_database

        try:
            assert_compatible_database(settings.database_url)
        except DatabaseVersionError as error:
            print(str(error), file=sys.stderr)
            return 1
        except Exception as error:
            print(f"Could not inspect the datastore: {error}", file=sys.stderr)
            return 1
        print("Datastore schema is compatible.")
        return 0

    if mode == "migrate":
        # Server one-shot provisioning (ADR-0062 §3 / ADR-0064): runs as
        # the owner role and exits — `serve` never migrates, and the
        # desktop profile keeps its local boot migrations. No local
        # bootstrap here: the compose migrate container carries no
        # desktop data dir.
        from app.core.config import SplitCredentialConfigError, settings

        if settings.database_url.startswith("sqlite"):
            print(
                "migrate is the server (PostgreSQL) mode; the desktop profile "
                "migrates locally at boot. Nothing was changed.",
                file=sys.stderr,
            )
            return 2
        from app.ops.provisioning import ProvisioningError, run_server_provisioning

        try:
            run_server_provisioning()
        except (ProvisioningError, SplitCredentialConfigError) as error:
            print(f"Provisioning failed: {error}", file=sys.stderr)
            return 1
        return 0

    from app.local import (
        bootstrap_environment,
        default_data_dir,
        run_migrations,
        seed_reference_data,
    )

    data_dir = default_data_dir()
    bootstrap_environment(data_dir)
    if mode == "app":
        # Desktop modes declare their channel capability before Settings
        # is imported.
        import os

        os.environ["CAREER_DESKTOP_MODE"] = "1"

    if mode == "restore":
        if len(args) != 2:
            print(USAGE, file=sys.stderr)
            return 2
        from app import backups

        archive = Path(args[1])
        if not archive.is_file():
            print(f"No such archive: {archive}", file=sys.stderr)
            return 1
        try:
            summary = backups.restore_backup(data_dir, archive)
        except RuntimeError as exc:
            print(f"Restore failed: {exc}", file=sys.stderr)
            return 1
        print(f"Restored from {archive.name}: {summary}")
        return 0

    # The datastore break guard must run before anything opens the database.
    from app.core.config import settings
    from app.storage.datastore_guard import DatastoreQuarantineError, guard_datastore

    try:
        guard_datastore(settings)
    except DatastoreQuarantineError as error:
        _report_startup_error(data_dir, error)
        return 1

    from app import backups

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
    seed_reference_data()

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
