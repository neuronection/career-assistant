#!/usr/bin/env python3
"""One-shot backfill: encrypt plaintext secret columns at rest.

Re-encrypts every stored secret that predates at-rest encryption (or was
written by a pre-rotation build) into the current ``enc::`` form:

* ``ai_providers.api_key_encrypted``
* ``mcp_bridges.token``
* encrypted fields inside ``app_settings.value`` JSON (VAPID ``private_key_enc``, web-tool GitHub ``token``)

Safe to re-run — values already in ``enc::`` form are skipped, and each
row is written only when it changes (idempotent; safe alongside normal
writes: an unchanged row is never touched).

Usage:
    cd <repo root>
    python3 scripts/encrypt_existing_secrets.py [--dry-run]

Runs against the configured career database (same env/.env resolution as
the app). Needs the DATA_KEY key ring resolvable — the same one the app
seals under (CAREER_DATA_KEY or the generated auth_keys.json).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.core.encryption import encrypt_secret, is_encrypted  # noqa: E402
from app.models.ai_provider_model import AIProvider  # noqa: E402
from app.models.mcp_bridge_model import AIMCPServer  # noqa: E402
from app.models.settings_model import AppSetting  # noqa: E402

VAPID_SETTING_KEY = "notifications.vapid"

# AppSetting rows carrying encrypted fields inside their JSON value.
SETTING_SECRET_FIELDS: dict[str, tuple[str, ...]] = {
    "notifications.vapid": ("private_key_enc",),
    "web.github_token": ("token",),
}


def _needs_seal(value: str | None) -> bool:
    return bool(value) and not is_encrypted(value)


async def backfill(dry_run: bool) -> int:
    sealed = 0
    async with AsyncSessionLocal() as db:
        # 1. AI provider API keys
        for row in (await db.execute(select(AIProvider))).scalars():
            if _needs_seal(row.api_key_encrypted):
                sealed += 1
                print(f"  ai_provider {row.id}: sealing api_key")
                if not dry_run:
                    row.api_key_encrypted = encrypt_secret(row.api_key_encrypted)

        # 2. MCP bridge tokens
        for row in (await db.execute(select(AIMCPServer))).scalars():
            if _needs_seal(row._token):
                sealed += 1
                print(f"  mcp_bridge {row.id}: sealing token")
                if not dry_run:
                    row._token = encrypt_secret(row._token)

        # 3. Encrypted fields inside app-setting JSON (VAPID, GitHub token, …)
        for setting_key, fields in SETTING_SECRET_FIELDS.items():
            for row in (
                await db.execute(select(AppSetting).where(AppSetting.key == setting_key))
            ).scalars():
                value = row.value or {}
                dirty = False
                for field in fields:
                    if _needs_seal(value.get(field)):
                        sealed += 1
                        print(f"  app_setting {setting_key}: sealing {field}")
                        if not dry_run:
                            if not dirty:
                                value = dict(value)
                                dirty = True
                            value[field] = encrypt_secret(value[field])
                if dirty and not dry_run:
                    row.value = value

        if not dry_run:
            await db.commit()
    return sealed


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would change; write nothing"
    )
    args = parser.parse_args()
    print(f"{'DRY RUN — ' if args.dry_run else ''}sealing plaintext secret columns…")
    sealed = await backfill(args.dry_run)
    if args.dry_run:
        print(f"{sealed} value(s) would be sealed.")
    else:
        print(f"{sealed} value(s) sealed. Re-run is a no-op.")
        print(
            "Next (rotation runbook, docs/dev/security.md): if this instance "
            "ever had a prior DATA_KEY, keep it in CAREER_DATA_KEY_PREVIOUS "
            "until every stored _kid… — career stores bare enc:: strings, so "
            "verify by a decrypt probe per secret surface before dropping it."
        )


if __name__ == "__main__":
    asyncio.run(main())
