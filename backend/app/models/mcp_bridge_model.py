"""MCP client bridge: admin-registered external MCP
servers whose tools become available namespaced (``mcp.<server>.<tool>``).

Servers are **disabled by default** and per-tool enabled; discovery is
explicit (refresh). Tool calls execute through the fastmcp client and
are audited + budgeted like every AI call (``ai_generations`` via the
``mcp_tool_call`` task).
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import decrypt_secret, encrypt_secret, mask_secret
from app.models.base import (
    Base,
    StructuredJSON,
    TZDateTime,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class AIMCPServer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One registered external MCP server."""

    __tablename__ = "ai_mcp_servers"
    __table_args__ = (
        UniqueConstraint("name", name="uq_ai_mcp_servers_name"),
        CheckConstraint("transport IN ('http', 'stdio')", name="transport_allowed"),
    )

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    transport: Mapped[str] = mapped_column(String(20), nullable=False, default="http")
    # http: the streamable-http endpoint; stdio: the command line.
    url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    command: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Bearer token for http servers (encrypted at rest, masked on read).
    _token: Mapped[Optional[str]] = mapped_column("token", String(1000), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Discovery snapshot: [{"name","description"}]; enablement is a
    # separate allowlist so a refresh never silently widens access.
    discovered_tools: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=list
    )
    enabled_tools: Mapped[list] = mapped_column(
        StructuredJSON, nullable=False, default=list
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        TZDateTime(), nullable=True
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)

    @property
    def token(self) -> str:
        return decrypt_secret(self._token) or ""

    @token.setter
    def token(self, value: str) -> None:
        self._token = encrypt_secret(value) if value else None

    @property
    def token_masked(self) -> str:
        return mask_secret(self._token) or ""

    def namespaced(self, tool_name: str) -> str:
        return f"mcp.{self.name}.{tool_name}"
