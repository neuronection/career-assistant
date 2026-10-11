"""§16 config surface (plan 16 P3d): every family knob is routable from
the deployment `.env` file as well as the process environment.

The kit's `AuthConfig.from_env` reads `os.environ` only — these cases
drive the real `_install_identity` with a `Settings` instance bound to a
temp `.env` file (the P3c `REGISTRATION_ENABLED` pattern) and assert the
values land in the installed kit config and the app rate limiter. OS
environment variables still win over the file.
"""

import asyncio

import pytest
from fastapi import FastAPI

_KNOB_ENV = (
    "CAREER_COOKIE_SECURE",
    "CAREER_AUTH_ACCESS_TTL_MINUTES",
    "CAREER_AUTH_REFRESH_TTL_DAYS",
    "CAREER_AUTH_REFRESH_ABSOLUTE_DAYS",
    "CAREER_AUTH_LOCKOUT_THRESHOLD",
    "CAREER_AUTH_LOCKOUT_MINUTES",
    "CAREER_TRUSTED_PROXY_COUNT",
    "CAREER_RATELIMIT_AUTH",
    "CAREER_RATELIMIT_AUTH_EMAIL",
    "CAREER_RATELIMIT_AI",
    "CAREER_RATELIMIT_MCP",
    "CAREER_RATELIMIT_DEFAULT",
    "CAREER_RATELIMIT_ENABLED",
    "CAREER_REGISTRATION_ENABLED",
)


def _settings_from_env_text(monkeypatch, tmp_path, text: str):
    from tests.settings_factory import settings_from_env_file

    env_file = tmp_path / ".env"
    env_file.write_text(text)
    for var in _KNOB_ENV:
        monkeypatch.delenv(var, raising=False)
    return settings_from_env_file(str(env_file))


async def test_sec16_matrix_reaches_kit_config_from_dotenv(monkeypatch, tmp_path):
    import app.auth.install as install_module

    fresh = _settings_from_env_text(
        monkeypatch,
        tmp_path,
        "\n".join(
            [
                "CAREER_COOKIE_SECURE=true",
                "CAREER_AUTH_ACCESS_TTL_MINUTES=45",
                "CAREER_AUTH_REFRESH_TTL_DAYS=14",
                "CAREER_AUTH_REFRESH_ABSOLUTE_DAYS=60",
                "CAREER_AUTH_LOCKOUT_THRESHOLD=3",
                "CAREER_AUTH_LOCKOUT_MINUTES=30",
                "CAREER_TRUSTED_PROXY_COUNT=2",
                "CAREER_RATELIMIT_AUTH=7",
                "CAREER_RATELIMIT_AUTH_EMAIL=11",
                "CAREER_REGISTRATION_ENABLED=false",
            ]
        )
        + "\n",
    )

    app = FastAPI()
    install_module.install_identity(app, fresh)
    config = app.state.auth.config

    assert config.cookie_secure is True
    assert config.access_ttl_minutes == 45
    assert config.refresh_ttl_days == 14
    assert config.refresh_absolute_days == 60
    assert config.lockout_threshold == 3
    assert config.lockout_minutes == 30
    assert config.trusted_proxy_count == 2
    assert config.registration_enabled is False
    # The same per-bucket ceilings feed the auth-kit's limiters.
    assert config.auth_rate_per_minute == 7
    assert config.auth_email_rate_per_minute == 11


async def test_sec16_env_beats_dotenv_file(monkeypatch, tmp_path):
    """OS environment wins over the .env file (per key)."""
    fresh = _settings_from_env_text(monkeypatch, tmp_path, "CAREER_AUTH_LOCKOUT_THRESHOLD=3\n")
    assert fresh.auth_lockout_threshold == 3, "file value resolves"

    from tests.settings_factory import settings_from_env_file

    monkeypatch.setenv("CAREER_AUTH_LOCKOUT_THRESHOLD", "9")
    os_wins = settings_from_env_file(str(tmp_path / ".env"))
    assert os_wins.auth_lockout_threshold == 9, "environment beats the file"


@pytest.mark.contract  # §18.22 — <P>_RATELIMIT_* ceilings routable from .env (R7/D5)
async def test_sec16_ratelimit_bounded_from_dotenv(monkeypatch, tmp_path):
    """`CAREER_RATELIMIT_*` per-bucket ceilings reach the mounted kit
    limiter (plan 21: Settings-routed ceilings, checked per request)."""
    from app.core.config import settings as global_settings
    from app.middleware import ratelimit_ceiling

    fresh = _settings_from_env_text(
        monkeypatch,
        tmp_path,
        "\n".join(
            [
                "CAREER_RATELIMIT_AUTH=7",
                "CAREER_RATELIMIT_AUTH_EMAIL=11",
                "CAREER_RATELIMIT_AI=13",
                "CAREER_RATELIMIT_MCP=17",
                "CAREER_RATELIMIT_DEFAULT=19",
                "CAREER_RATELIMIT_ENABLED=false",
            ]
        )
        + "\n",
    )
    monkeypatch.setattr(global_settings, "ratelimit_auth", fresh.ratelimit_auth)
    monkeypatch.setattr(global_settings, "ratelimit_auth_email", fresh.ratelimit_auth_email)
    monkeypatch.setattr(global_settings, "ratelimit_ai", fresh.ratelimit_ai)
    monkeypatch.setattr(global_settings, "ratelimit_mcp", fresh.ratelimit_mcp)
    monkeypatch.setattr(global_settings, "ratelimit_default", fresh.ratelimit_default)
    monkeypatch.setattr(global_settings, "ratelimit_enabled", fresh.ratelimit_enabled)

    # The policy's ceiling callable resolves the Settings fields live.
    assert ratelimit_ceiling("AUTH") == 7
    assert ratelimit_ceiling("AUTH_EMAIL") == 11
    assert ratelimit_ceiling("AI") == 13
    assert ratelimit_ceiling("MCP") == 17
    assert ratelimit_ceiling("DEFAULT") == 19
    assert fresh.ratelimit_enabled is False
    # §16 names resolve through the kit knob map.
    assert fresh.ratelimit_auth == 7
    assert fresh.ratelimit_ai == 13

    # End-to-end over the mounted policy: 7 allowed, the 8th refused —
    # .env-only ceilings are enforced (R7).
    import threading

    from app.middleware import RATE_LIMIT_POLICY

    monkeypatch.setattr(global_settings, "ratelimit_enabled", True)
    monkeypatch.setattr(global_settings, "ratelimit_default", 7)

    def _tick() -> int | None:
        outcome: dict[str, int | None] = {}

        def _run() -> None:
            outcome["retry"] = asyncio.run(RATE_LIMIT_POLICY.check("DEFAULT", "1.2.3.4"))

        worker = threading.Thread(target=_run)
        worker.start()
        worker.join(timeout=10)
        return outcome["retry"]

    for _ in range(7):
        assert _tick() is None
    assert _tick() is not None


@pytest.mark.contract  # §18.19 — trusted-proxy identity reaches the limiter (R2/R3)
async def test_sec16_trusted_proxy_count_reaches_kit_and_client_identity(monkeypatch, tmp_path):
    import app.auth.install as install_module
    from app.core.config import settings as global_settings
    from app.middleware import client_identity

    fresh = _settings_from_env_text(monkeypatch, tmp_path, "CAREER_TRUSTED_PROXY_COUNT=1\n")
    monkeypatch.setattr(global_settings, "trusted_proxy_count", fresh.trusted_proxy_count)

    app = FastAPI()
    install_module.install_identity(app, fresh)
    assert app.state.auth.config.trusted_proxy_count == 1

    scope = {
        "client": ("203.0.113.9", 5),
        "headers": [(b"x-forwarded-for", b"1.1.1.1")],
    }
    assert client_identity(scope) == "1.1.1.1", "the trusted rightmost hop wins"


async def test_sec16_matrix_reaches_kit_config_from_os_environ(monkeypatch):
    """Process-environment routing (no .env file involved)."""
    import app.auth.install as install_module

    for var in _KNOB_ENV:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CAREER_COOKIE_SECURE", "true")
    monkeypatch.setenv("CAREER_AUTH_ACCESS_TTL_MINUTES", "25")
    monkeypatch.setenv("CAREER_TRUSTED_PROXY_COUNT", "1")

    from tests.settings_factory import settings_from_env_file

    fresh = settings_from_env_file(None)

    app = FastAPI()
    install_module.install_identity(app, fresh)
    config = app.state.auth.config
    assert config.cookie_secure is True
    assert config.access_ttl_minutes == 25
    assert config.trusted_proxy_count == 1
