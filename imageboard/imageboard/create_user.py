"""Create a local HTTP Basic user without exposing registration."""

import argparse
import getpass
import os
import unicodedata

import psycopg
from werkzeug.security import generate_password_hash


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--admin", action="store_true")
    args = parser.parse_args()
    password = getpass.getpass()
    if (
        not 3 <= len(args.username) <= 100
        or args.username != args.username.strip()
        or ":" in args.username
        or any(unicodedata.category(char) == "Cc" for char in args.username)
        or not 14 <= len(password) <= 256
        or any(unicodedata.category(char) == "Cc" for char in password)
    ):
        parser.error("username must be 3-100 characters without colon/control characters/surrounding whitespace; password must be 14-256 characters without control characters")
    database_url = os.environ["IMAGEBOARD_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(734921, 1)")
        cursor.execute('SELECT 1 FROM "user" WHERE name = %s', (args.username,))
        if cursor.fetchone():
            parser.error("username already exists")
        cursor.execute(
            'INSERT INTO "user" (name, password, registered, karma, privileges, banned) '
            "VALUES (%s, %s, NOW(), 0, %s, FALSE) RETURNING id",
            (
                args.username,
                generate_password_hash(password, method="scrypt:32768:8:1"),
                "admin" if args.admin else "user",
            ),
        )
        user_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO audit_event (actor_id, action, object_type, object_id, created_at) "
            "VALUES (NULL, 'create_user_cli', 'user', %s, NOW())",
            (str(user_id),),
        )


if __name__ == "__main__":
    main()
