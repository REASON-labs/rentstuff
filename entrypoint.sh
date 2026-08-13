#!/bin/sh
set -e
mkdir -p "$(dirname "$RENTSTUFF_DB")"
# idempotent: schema uses CREATE TABLE IF NOT EXISTS
flask --app wsgi init-db
exec "$@"
