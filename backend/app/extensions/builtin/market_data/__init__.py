"""Builtin market-data sources (plan 127 §3.2): one package per source.

Every bundle carries its own ``manifest.json`` (the ``extension/v1``
connector envelope — the charter's item-schema contract for external data
sources) and its provider class. Adding a source means adding a package
here plus its line in ``BUILTINS``; core (``app.extensions.market_data``)
never names a source.
"""

from app.extensions.builtin.market_data.world_bank import WorldBankWdiProvider
from app.extensions.market_data import MarketDataProvider

BUILTINS: list[MarketDataProvider] = [WorldBankWdiProvider()]
