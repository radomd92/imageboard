"""Create a local HTTP Basic user without exposing registration."""

import argparse
import getpass

from sqlalchemy import select
from werkzeug.security import generate_password_hash

from .api import SessionLocal, User


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--password")
    parser.add_argument("--admin", action="store_true")
    args = parser.parse_args()
    password = args.password or getpass.getpass()
    if not 3 <= len(args.username) <= 100 or len(password) < 14:
        parser.error("username must be 3-100 characters; password must be at least 14 characters")
    with SessionLocal() as session:
        if session.scalar(select(User).where(User.name == args.username)):
            parser.error("username already exists")
        session.add(User(
            name=args.username,
            password=generate_password_hash(password, method="scrypt"),
            privileges="admin" if args.admin else "user",
            banned=False,
        ))
        session.commit()


if __name__ == "__main__":
    main()
