"""§16 config surface (plan 16 P3d): every family knob is routable from
the deployment `.env` file as well as the process environment.

The kit's `AuthConfig.from_env` reads `os.environ` only — these cases
drive the real `_install_identity` with a `Settings` instance bound to a
temp `.env` file (the P3c `REGISTRATION_ENABLED` pattern) and assert the
values land in the installed kit config and the app rate limiter. OS
environment variables still win over the file.
"""

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
    "COOKIE_SECURE",
    "AUTH_ACCESS_TTL_MINUTES",
    "AUTH_REFRESH_TTL_DAYS",
    "AUTH_REFRESH_ABSOLUTE_DAYS",
    "AUTH_LOCKOUT_THRESHOLD",
    "AUTH_LOCKOUT_MINUTES",
    "TRUSTED_PROXY_COUNT",
    "AUTH_RATE_LIMIT",
    "AUTH_EMAIL_RATE_LIMIT",
    "AI_RATE_LIMIT",
    "MCP_RATE_LIMIT",
    "DEFAULT_RATE_LIMIT",
    "RATE_LIMIT_ENABLED",
    "CAREER_REGISTRATION_ENABLED",
    "REGISTRATION_ENABLED",
)


def _settings_from_env_text(monkeypatch, tmp_path, text: str):
    from app.core.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text(text)
    for var in _KNOB_ENV:
        monkeypatch.delenv(var, raising=False)
    return Settings(_env_file=str(env_file))


async def test_sec16_matrix_reaches_kit_config_from_dotenv(monkeypatch, tmp_path):
    import app.main as main_module

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
    monkeypatch.setattr(main_module, "settings", fresh)

    app = FastAPI()
    main_module._install_identity(app)
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
    fresh = _settings_from_env_text(
        monkeypatch, tmp_path, "CAREER_AUTH_LOCKOUT_THRESHOLD=3\n"
    )
    assert fresh.AUTH_LOCKOUT_THRESHOLD == 3, "file value resolves"

    from app.core.config import Settings

    monkeypatch.setenv("CAREER_AUTH_LOCKOUT_THRESHOLD", "9")
    os_wins = Settings(_env_file=str(tmp_path / ".env"))
    assert os_wins.AUTH_LOCKOUT_THRESHOLD == 9, "environment beats the file"


async def test_sec16_ratelimit_bounded_from_dotenv(monkeypatch, tmp_path):
    """`CAREER_RATELIMIT_*` per-bucket ceilings reach the app limiter."""
    from app.core.config import settings as global_settings
    from app.core.ratelimit import SlidingWindowRateLimiter

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
    monkeypatch.setattr(global_settings, "AUTH_RATE_LIMIT", fresh.AUTH_RATE_LIMIT)
    monkeypatch.setattr(
        global_settings, "AUTH_EMAIL_RATE_LIMIT", fresh.AUTH_EMAIL_RATE_LIMIT
    )
    monkeypatch.setattr(global_settings, "AI_RATE_LIMIT", fresh.AI_RATE_LIMIT)
    monkeypatch.setattr(global_settings, "MCP_RATE_LIMIT", fresh.MCP_RATE_LIMIT)
    monkeypatch.setattr(global_settings, "DEFAULT_RATE_LIMIT", fresh.DEFAULT_RATE_LIMIT)
    monkeypatch.setattr(global_settings, "RATE_LIMIT_ENABLED", fresh.RATE_LIMIT_ENABLED)

    limiter = SlidingWindowRateLimiter()
    assert limiter._limits("auth") == (7, 60)
    assert limiter._limits("auth_email") == (11, 60)
    assert limiter._limits("ai") == (13, 60)
    assert limiter._limits("mcp") == (17, 60)
    assert limiter._limits("default") == (19, 60)
    assert fresh.RATE_LIMIT_ENABLED is False
    # §16 names resolve the same values as the legacy unprefixed ones.
    assert fresh.AUTH_RATE_LIMIT == 7
    assert fresh.AI_RATE_LIMIT == 13


def test_sec16_legacy_unprefixed_ratelimit_names_still_work(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("AUTH_RATE_LIMIT", "5")
    monkeypatch.setenv("DEFAULT_RATE_LIMIT", "6")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    for var in (
        "CAREER_RATELIMIT_AUTH",
        "CAREER_RATELIMIT_DEFAULT",
        "CAREER_RATELIMIT_ENABLED",
    ):
        monkeypatch.delenv(var, raising=False)
    resolved = Settings(_env_file=None)
    assert resolved.AUTH_RATE_LIMIT == 5
    assert resolved.DEFAULT_RATE_LIMIT == 6
    assert resolved.RATE_LIMIT_ENABLED is False


async def test_sec16_trusted_proxy_count_reaches_kit_and_client_identity(
    monkeypatch, tmp_path
):
    import app.main as main_module
    from app.core.config import settings as global_settings
    from app.core.ratelimit import client_identity

    fresh = _settings_from_env_text(
        monkeypatch, tmp_path, "CAREER_TRUSTED_PROXY_COUNT=1\n"
    )
    monkeypatch.setattr(main_module, "settings", fresh)
    monkeypatch.setattr(
        global_settings, "TRUSTED_PROXY_COUNT", fresh.TRUSTED_PROXY_COUNT
    )

    app = FastAPI()
    main_module._install_identity(app)
    assert app.state.auth.config.trusted_proxy_count == 1

    scope = {
        "client": ("203.0.113.9", 5),
        "headers": [(b"x-forwarded-for", b"1.1.1.1")],
    }
    assert client_identity(scope) == "1.1.1.1", "the trusted rightmost hop wins"


async def test_sec16_matrix_reaches_kit_config_from_os_environ(monkeypatch):
    """Process-environment routing (no .env file involved)."""
    import app.main as main_module

    for var in _KNOB_ENV:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CAREER_COOKIE_SECURE", "true")
    monkeypatch.setenv("CAREER_AUTH_ACCESS_TTL_MINUTES", "25")
    monkeypatch.setenv("CAREER_TRUSTED_PROXY_COUNT", "1")

    from app.core.config import Settings

    fresh = Settings(_env_file=None)
    monkeypatch.setattr(main_module, "settings", fresh)

    app = FastAPI()
    main_module._install_identity(app)
    config = app.state.auth.config
    assert config.cookie_secure is True
    assert config.access_ttl_minutes == 25
    assert config.trusted_proxy_count == 1
