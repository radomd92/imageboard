#!/bin/sh
set -eu

alembic -c migrations/alembic.ini upgrade head
exec "$@"
