#!/usr/bin/env bash
# Rotate a local HTTP Basic password without exposing it in arguments or environment variables.
set -euo pipefail

username="${1:-mpandrindra}"

if [[ $# -gt 1 ]]; then
    printf 'Usage: %s [username]\n' "$0" >&2
    exit 2
fi

read -r -s -p "New password for ${username}: " password
printf '\n'
read -r -s -p 'Confirm password: ' confirmation
printf '\n'

if [[ "$password" != "$confirmation" ]]; then
    printf 'Passwords do not match.\n' >&2
    exit 1
fi

unset confirmation
trap 'unset password' EXIT

compose=(docker-compose)
if ! docker-compose ps >/dev/null 2>&1; then
    compose=(sudo -n docker-compose)
fi

# Password is provided on stdin only; it never appears in the process arguments or environment.
printf '%s\n' "$password" | "${compose[@]}" run --rm -T --entrypoint python migrator -c '
import sys

import os
import unicodedata

import psycopg
from werkzeug.security import generate_password_hash

username = sys.argv[1]
password = sys.stdin.readline().rstrip("\n")

if not 14 <= len(password) <= 256 or any(unicodedata.category(char) == "Cc" for char in password):
    raise SystemExit("Password must contain 14-256 characters without control characters")

database_url = os.environ["IMAGEBOARD_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
    cursor.execute("SELECT pg_advisory_xact_lock(734921, 1)")
    cursor.execute("SELECT id FROM \"user\" WHERE name = %s", (username,))
    account = cursor.fetchone()
    if account is None:
        raise SystemExit("User not found")
    cursor.execute(
        "UPDATE \"user\" SET password = %s WHERE name = %s",
        (generate_password_hash(password, method="scrypt:32768:8:1"), username),
    )
    cursor.execute(
        "INSERT INTO audit_event (actor_id, action, object_type, object_id, created_at) "
        "VALUES (NULL, %s, %s, %s, NOW())",
        ("reset_user_password_cli", "user", str(account[0])),
    )
' "$username"

unset password
trap - EXIT

printf 'Password rotated. Close authenticated browser windows.\n'
