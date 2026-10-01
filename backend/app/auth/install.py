"""Family auth-kit installation (identity-auth §4/§5/§8/§10/§11).

`install_identity` mounts nx_auth at its exact contract paths and wires
the ADR-0028 glue:

- init-only instance modes via `nx_auth.instance.initialize_instance`
  (DB authoritative, env flips ignored loudly, fail-closed; §4);
- the §16 knob set routed from `Settings` through
  `nx_auth.config.knob_overrides` so deployment `.env` values reach the
  kit config exactly like process-environment ones (OS env wins per key;
  plan 20 B2);
- one KeyRing for signing AND secrets at rest (§8);
- desktop entrypoint: the per-boot shell secret becomes the §11 request
  gate (and keeps marking `?shell=` documents for the desktop CSP
  variant); DIM exchange mounts in desktop mode only.

In-tree auth routes are gone (same-commit delete) — `/api/v1/auth/*`,
`/api/v1/me/*` and `/api/v1/admin/*` come from the kit at their exact
§12 paths.
"""

from __future__ import annotations

import logging
import os
from dataclasses import replace
from typing import Literal

from fastapi import FastAPI
from nx_auth import AuthConfig
from nx_auth import install as install_auth_kit
from nx_auth.config import knob_overrides
from nx_auth.instance import IdentityMode, initialize_instance

from app.core.config import settings

logger = logging.getLogger(__name__)

# Kit §16 env suffix → career `Settings` field. Only the two rate-limit
# knobs differ in name today; Phase 4 (prefixed-only + snake_case fields)
# makes every field mirror its suffix and this map dies.
_KNOB_FIELD_ALIASES = {
    "RATELIMIT_AUTH": "AUTH_RATE_LIMIT",
    "RATELIMIT_AUTH_EMAIL": "AUTH_EMAIL_RATE_LIMIT",
}


def _settings_knob(name: str) -> object | None:
    suffix = name.removeprefix("CAREER_")
    return getattr(settings, _KNOB_FIELD_ALIASES.get(suffix, suffix), None)


def install_identity(application: FastAPI) -> None:
    """Mount the family auth-kit (identity-auth §4/§5/§8/§10/§11)."""
    from app.auth.stores import (
        CareerAuditSink,
        CareerInstanceStore,
        CareerProfileStore,
        CareerSessionStore,
        CareerUserStore,
    )
    from app.core.database import AuthSessionLocal
    from app.core.keys import keyring

    instance_store = CareerInstanceStore(AuthSessionLocal)
    effective_auth_mode = initialize_instance(
        instance_store,
        identity_mode=settings.identity_mode,
        auth_mode_env=settings.AUTH_MODE,
        demo_mode_env=settings.DEMO_MODE,
        product="CAREER",
    )

    # §11 gate arms only when a shell actually attaches: shell.py sets
    # CAREER_SHELL=1 before create_app. Shell-less desktop dev (run-dev.sh:
    # uvicorn + vite, ADR-0023) has no shell to hold the per-boot token or
    # carry it as `?shell=` — arming the gate there would 403 every auth
    # request from the dev SPA ("invalid shell token").
    shell_attached = (
        settings.identity_mode is IdentityMode.DESKTOP
        and os.environ.get("CAREER_SHELL") == "1"
    )
    if settings.identity_mode is IdentityMode.DESKTOP and not shell_attached:
        # Fail loud, not silent: this is the shell-less dev shape (ADR-0023)
        # — ungated + open-auth DIM. Safe on loopback only; a non-loopback
        # bind here exposes an owner-level API to the network.
        logger.warning(
            "desktop identity WITHOUT an attached shell (CAREER_SHELL unset) — "
            "the X-Shell-Token gate is DISARMED (§11 / ADR-0023); bind the "
            "server to loopback only"
        )
        if effective_auth_mode != "open":
            # Init-only trap: a profile stamped `authenticated` under older
            # server-identity dev runs keeps it — the SPA shows the login
            # gate even though the §11 gate is disarmed (§4: mode changes
            # are admin actions, never launch-time).
            logger.warning(
                "local profile auth_mode=%r — the login gate applies to this "
                "instance; `./scripts/run-dev.sh --reset` wipes the local "
                "profile and re-initializes it open (backups kept)",
                effective_auth_mode,
            )
    shell_secret: str | None = None
    if shell_attached:
        # One per-boot secret serves both desktop gates (§11): the
        # X-Shell-Token request gate and the `?shell=` CSP marker.
        from app.desktop.shell_token import issue

        shell_secret = issue()

    kit_identity: Literal["server", "desktop"] = (
        "desktop" if settings.identity_mode is IdentityMode.DESKTOP else "server"
    )
    config = AuthConfig.from_env(
        "CAREER",
        iss="career",
        identity_mode=kit_identity,
        require_shell_secret=shell_secret is not None,
        # §16 knobs resolved through Settings (ADR-0028): the `.env` file
        # and the process environment both reach the kit config (OS env
        # wins per key) — the kit's own `os.environ` read is the fallback.
        **knob_overrides("CAREER", _settings_knob),
    )
    config = replace(
        config,
        # Public instance facts (P3e demo badge) must be readable pre-login.
        auth_exempt_prefixes=(*config.auth_exempt_prefixes, "/api/v1/instance"),
    )
    install_auth_kit(
        application,
        config=config,
        # One KeyRing for signing AND secrets at rest (§8): the same
        # resolution `app.core.encryption` encrypts under.
        ring=keyring(),
        users=CareerUserStore(AuthSessionLocal),
        sessions=CareerSessionStore(AuthSessionLocal),
        instance=instance_store,
        profiles=CareerProfileStore(AuthSessionLocal),
        audit=CareerAuditSink(AuthSessionLocal),
        shell_secret=shell_secret,
        owner_email="owner@local",
    )
