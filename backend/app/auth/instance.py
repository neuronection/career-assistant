"""Instance access-mode initialization (identity-auth §4).

The DB is authoritative: `instance_settings.auth_mode` is written ONLY
when initializing an empty DB (first boot). After that, env/CLI flips
(`CAREER_AUTH_MODE`, `CAREER_DEMO_MODE`) are ignored with a loud
warning. Unknown values fail closed to `authenticated`; server
entrypoints never run `open` (§4.4).
"""

from __future__ import annotations

import logging

from nx_auth.instance import InstanceMode
from nx_auth.protocols import InstanceStore

logger = logging.getLogger(__name__)

VALID_AUTH_MODES: tuple[str, ...] = tuple(mode.value for mode in InstanceMode)


def initialize_instance(
    store: InstanceStore,
    *,
    identity_mode: str,
    auth_mode_env: str,
    demo_mode_env: bool,
) -> str:
    """Seed `instance_settings` on an empty DB; return the effective mode.

    - empty DB ⇒ write `auth_mode` (env value if legal; else the §4
      default: `open` on desktop, `authenticated` on server) and
      `demo_mode` (init-only, §13);
    - `open` on a server entrypoint is never legal (§4.4) — the write
      becomes `authenticated` with a loud warning;
    - existing DB ⇒ the stored value wins; a mismatching env is ignored
      with a loud warning (post-init flips are not a thing).
    """
    env_mode = auth_mode_env.strip().lower()
    if env_mode and env_mode not in VALID_AUTH_MODES:
        logger.warning(
            "CAREER_AUTH_MODE=%r is not a valid mode (%s) — failing closed to authenticated",
            auth_mode_env,
            "/".join(VALID_AUTH_MODES),
        )
        env_mode = InstanceMode.AUTHENTICATED.value

    stored = store.get("auth_mode")
    if stored is None:
        mode = env_mode or (
            InstanceMode.OPEN.value
            if identity_mode == "desktop"
            else InstanceMode.AUTHENTICATED.value
        )
        if identity_mode != "desktop" and mode == InstanceMode.OPEN.value:
            logger.warning(
                "CAREER_AUTH_MODE=open is not legal on a server entrypoint "
                "(identity-auth §4.4) — initializing as authenticated"
            )
            mode = InstanceMode.AUTHENTICATED.value
        store.set("auth_mode", mode)
        store.set("demo_mode", "true" if demo_mode_env else "false")
        logger.info(
            "instance_settings initialized: auth_mode=%s (identity_mode=%s)",
            mode,
            identity_mode,
        )
        return mode

    if env_mode and env_mode != stored:
        logger.warning(
            "CAREER_AUTH_MODE=%s ignored — instance_settings.auth_mode=%s is "
            "authoritative (identity-auth §4: mode changes are authenticated "
            "admin actions, never launch-time)",
            env_mode,
            stored,
        )
    if demo_mode_env and store.get("demo_mode") != "true":
        logger.warning(
            "CAREER_DEMO_MODE=true ignored — instance_settings.demo_mode is "
            "authoritative after initialization (identity-auth §13)"
        )
    return stored
