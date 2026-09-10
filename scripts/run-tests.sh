#!/bin/bash
# Backend test runner. Full suite by default, or pass a path.
set -e
cd "$(dirname "$0")/../backend"
if [ -d venv ]; then source venv/bin/activate; fi
pytest tests/${1:+$1}
