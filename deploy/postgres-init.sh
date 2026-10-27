#!/bin/sh
set -eu
export PLUSFOLIO_DB_PASSWORD="$(cat /run/secrets/db_password)"
psql --username postgres --dbname postgres -v ON_ERROR_STOP=1 <<'SQL'
\getenv app_password PLUSFOLIO_DB_PASSWORD
CREATE ROLE plusfolio LOGIN PASSWORD :'app_password';
CREATE DATABASE plusfolio OWNER plusfolio;
\connect plusfolio
CREATE EXTENSION vector;
CREATE EXTENSION pg_trgm;
SQL
unset PLUSFOLIO_DB_PASSWORD
