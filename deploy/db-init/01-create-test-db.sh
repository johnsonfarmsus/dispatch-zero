#!/bin/bash
# Postgres init script — runs ONCE on first boot of an empty data volume.
# Creates the dispatchzero_test database used by the pytest suite.
#
# On the production VPS this no-ops because the volume already has data; the
# test DB was created manually long ago. In CI (fresh volume every run) and
# for fresh local clones, this is what gets the test suite working without
# any extra steps.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE dispatchzero_test;
EOSQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname dispatchzero_test <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS postgis;
EOSQL
