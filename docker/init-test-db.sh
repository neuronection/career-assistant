#!/bin/bash
# Creates the companion test database next to the dev DB on first boot.
set -e
TEST_DB="${POSTGRES_TEST_DB:-career_test}"
echo "Creating test database '$TEST_DB' if missing..."
psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-career}" -d "${POSTGRES_DB:-career}" <<-SQL
  SELECT 'CREATE DATABASE ${TEST_DB}'
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${TEST_DB}')\gexec
SQL
echo "Test database ready."
