"""Economic-context services (plan 127): region resolution, coverage, reducers."""

from app.services.econ.coverage import resolve_coverage
from app.services.econ.regions import normalize_place, remember_resolution, resolve_region

__all__ = ["normalize_place", "remember_resolution", "resolve_coverage", "resolve_region"]
