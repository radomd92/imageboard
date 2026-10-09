"""Create a local HTTP Basic user without exposing registration."""

import argparse
import getpass
import os

import psycopg
from werkzeug.security import generate_password_hash


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--admin", action="store_true")
    args = parser.parse_args()
    password = getpass.getpass()
    if not 3 <= len(args.username) <= 100 or len(password) < 14:
        parser.error("username must be 3-100 characters; password must be at least 14 characters")
    database_url = os.environ["IMAGEBOARD_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute('SELECT 1 FROM "user" WHERE name = %s', (args.username,))
        if cursor.fetchone():
            parser.error("username already exists")
        cursor.execute(
            'INSERT INTO "user" (name, password, registered, karma, privileges, banned) '
            "VALUES (%s, %s, NOW(), 0, %s, FALSE)",
            (
                args.username,
                generate_password_hash(password, method="scrypt"),
                "admin" if args.admin else "user",
            ),
        )


if __name__ == "__main__":
    main()
