import os

os.environ["IMAGEBOARD_DATABASE_URL"] = "sqlite:///./test.db"

import pytest
from fastapi.testclient import TestClient
from werkzeug.security import generate_password_hash

from imageboard.api import Base, SessionLocal, User, app, engine


@pytest.fixture
def client():
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        session.add(User(
            name="member",
            password=generate_password_hash("member password is long enough", method="scrypt"),
            privileges="admin",
            banned=False,
        ))
        session.commit()
    yield TestClient(app)
    Base.metadata.drop_all(engine)
