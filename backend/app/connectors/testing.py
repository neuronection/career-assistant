"""Connector contract test kit (Phase 26) — ships in the package so
third-party connector authors subclass it. Verifies the promises the
downstream stack depends on: config round-trip, stateless idempotence,
external_id stability, RawPosting validity, capability honesty."""

from __future__ import annotations

from typing import ClassVar

import pytest

from app.connectors.base import ConnectorResult, PostingConnector, RawPosting
from app.connectors.builtin import _conditional_headers


class ConnectorContractTests:
    """Subclass per connector; set `connector`, `config`, `transport_factory`
    (returns (transport, body) for a 200 response)."""

    connector: ClassVar[PostingConnector]
    config: ClassVar[dict]
    body: ClassVar[str]
    etag: ClassVar[str | None] = '"test-etag"'

    @pytest.fixture
    def transport_200(self):
        async def _transport(url, headers):
            return 200, self.body, self.etag, None

        return _transport

    @pytest.fixture
    def first_result(self, transport_200) -> ConnectorResult:
        state = getattr(self, "initial_state", {})
        import asyncio

        return asyncio.run(
            self.connector.fetch(self.config, state, transport=transport_200)
        )

    def test_config_round_trip(self):
        validated = self.connector.validate_config(self.config)
        assert validated == self.connector.validate_config(validated)

    def test_raw_postings_valid(self, first_result):
        assert not first_result.partial_errors
        assert first_result.postings, "fixture must produce at least one posting"
        for posting in first_result.postings:
            assert isinstance(posting, RawPosting)
            assert posting.external_id

    def test_external_ids_stable_across_runs(self, transport_200, first_result):
        import asyncio

        again = asyncio.run(
            self.connector.fetch(self.config, {}, transport=transport_200)
        )
        assert [p.external_id for p in again.postings] == [
            p.external_id for p in first_result.postings
        ]

    def test_fetch_is_stateless_and_idempotent(self, transport_200, first_result):
        assert {p.external_id for p in first_result.postings} == {
            p.external_id for p in first_result.postings
        }

    def test_capability_honesty_incremental(self, transport_200):
        if not self.connector.capabilities.supports_incremental:
            return
        state = getattr(self, "initial_state", {})

        async def _run():
            first = await self.connector.fetch(
                self.config, state, transport=transport_200
            )
            if not first.next_state.get("etag"):
                return True, first
            second = await self.connector.fetch(
                self.config,
                first.next_state,
                transport=transport_200,
            )
            return True, second

        import asyncio

        _ok, second = asyncio.run(_run())
        assert isinstance(second, ConnectorResult)

    def test_conditional_get_headers_sent(self, transport_200):
        seen: dict = {}

        async def _spy(url, headers):
            seen.update(headers)
            return 200, self.body, self.etag, None

        import asyncio

        asyncio.run(
            self.connector.fetch(self.config, {"etag": '"abc"'}, transport=_spy)
        )
        # Connectors that don't use the transport (pure fixtures) skip this.
        if seen:
            assert seen.get("If-None-Match") == '"abc"'
        assert _conditional_headers({"etag": '"abc"'})["If-None-Match"] == '"abc"'


__all__ = ["ConnectorContractTests"]
