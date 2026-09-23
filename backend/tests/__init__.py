"""Test package bootstrap.

Runs pytest-xdist's per-worker database routing before ``tests.conftest``
imports the app engines — see ``xdist_routing.py`` for the why.
"""

from .xdist_routing import route_worker_database

route_worker_database()
