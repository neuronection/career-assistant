#!/bin/bash
# Creates the companion test database next to the dev DB on first boot.
#
# ADR-0022 (amended 2026-09-30): the database is `neuronection_career`, the
# bootstrap role `neuronection_career_owner` and the companion test database
# `neuronection_career_test` that pytest runs against.
set -e
TEST_DB="${POSTGRES_TEST_DB:-neuronection_career_test}"
echo "Creating test database '$TEST_DB' if missing..."
psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-neuronection_career_owner}" -d "${POSTGRES_DB:-neuronection_career}" <<-SQL
  SELECT 'CREATE DATABASE ${TEST_DB}'
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${TEST_DB}')\gexec
SQL
echo "Test database ready."
