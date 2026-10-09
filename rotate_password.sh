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

from sqlalchemy import select
from werkzeug.security import generate_password_hash

from imageboard.api import SessionLocal, User

username = sys.argv[1]
password = sys.stdin.readline().rstrip("\n")

if len(password) < 14:
    raise SystemExit("Password must contain at least 14 characters")

with SessionLocal() as session:
    user = session.scalar(select(User).where(User.name == username))
    if user is None:
        raise SystemExit("User not found")
    user.password = generate_password_hash(password, method="scrypt")
    session.commit()
' "$username"

unset password
trap - EXIT

"${compose[@]}" restart app
printf 'Password rotated. Close authenticated browser windows.\n'
