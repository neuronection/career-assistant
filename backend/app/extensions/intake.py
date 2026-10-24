"""Non-posting bundled intake extensions (plan 122 Phase 3).

The GitHub intake connector turns a student's public repositories into
project/achievement DRAFTS — never active rows. It is a bundled T1
extension with the same file-manifest law and registration gate as posting
connectors, but it lives in its own registry because it does not emit
postings (the connector SDK's item type is a vacancy).
"""

from __future__ import annotations

from app.core.errors import ValidationError
from app.extensions import registry
from app.extensions.sdk import (
    ConnectorCapabilities,
    ConnectorResult,
    EmptyConfig,
    PostingConnector,
)


class GithubIntake(PostingConnector):
    """GitHub repositories → profile drafts (review-first intake).

    The manifest is the law: ``builtin/github_intake/manifest.json`` declares
    the ``api.github.com`` scope. Fetching happens in
    :mod:`app.services.integrations.github_intake_service` over the guarded transport;
    this class exists so registration validates the bundle like every other
    bundled extension.
    """

    key = "github_intake"
    title = "GitHub repositories"
    docs_url = "https://docs.career-assistant.local/connectors/github-intake"
    capabilities = ConnectorCapabilities(
        network_scopes=["api.github.com"],
        supports_incremental=True,
        max_requests_per_minute=30,
    )

    def config_model(self) -> type[EmptyConfig]:
        return EmptyConfig

    async def fetch(self, config, state, *, transport=None, secrets=None, **_kw) -> ConnectorResult:
        raise NotImplementedError("the GitHub intake is driven by its service, not a posting sync")


_INTAKE: list[PostingConnector] = [GithubIntake()]


def list_intake() -> list[dict]:
    """Registered intake extensions with validated manifests."""
    entries = []
    for extension in _INTAKE:
        manifest = registry.validate_manifest(extension)
        entries.append(
            {
                "key": extension.key,
                "title": extension.title,
                "docs_url": extension.docs_url,
                "capabilities": extension.capabilities.model_dump(mode="json"),
                "manifest": manifest,
            }
        )
    return entries


def get_intake(key: str) -> PostingConnector:
    for extension in _INTAKE:
        if extension.key == key:
            return extension
    raise ValidationError(f"Unknown intake extension: {key}")


__all__ = ["GithubIntake", "get_intake", "list_intake"]
