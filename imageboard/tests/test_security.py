from imageboard import api
from imageboard.api import Image, SessionLocal

AUTH = ("member", "member password is long enough")


def test_api_requires_basic_auth(client):
    response = client.get("/api/images/1")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic"


def test_context_round_trip(client):
    with SessionLocal() as session:
        session.add(Image(id=1, image_path="album$example.jpg", name="Example", file_size=10, hits=0))
        session.commit()
    response = client.post("/api/images/1/context", auth=AUTH, json={"tags": ["Travel"], "comment": "Sunset"})
    assert response.status_code == 200
    assert response.json()["tags"] == ["travel"]
    assert response.json()["comments"][0]["text"] == "Sunset"


def test_file_redirect_requires_indexed_path(client, monkeypatch, tmp_path):
    media_file = tmp_path / "album" / "example.jpg"
    media_file.parent.mkdir()
    media_file.write_bytes(b"example")
    monkeypatch.setattr(api, "MEDIA_ROOT", tmp_path.resolve())
    with SessionLocal() as session:
        session.add(Image(id=1, image_path="album$example.jpg", name="Example", file_size=10, hits=0))
        session.commit()
    response = client.get("/api/images/1/file", auth=AUTH, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/media/album/example.jpg"


def test_missing_file_queues_asynchronous_deindex(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api, "MEDIA_ROOT", tmp_path.resolve())
    with SessionLocal() as session:
        session.add(Image(id=1, image_path="album$missing.jpg", name="Missing", file_size=10, hits=0))
        session.commit()

    response = client.get("/api/images/1/file", auth=AUTH, follow_redirects=False)

    assert response.status_code == 404
    with SessionLocal() as session:
        job = session.scalar(api.select(api.IndexJob))
    assert job is not None
    assert job.root_path == "album$missing.jpg"
    assert job.status == "pending"


def test_list_images_is_paginated(client):
    with SessionLocal() as session:
        session.add(Image(id=1, image_path="album$example.jpg", name="Example", file_size=10, hits=0))
        session.commit()
    response = client.get("/api/images", auth=AUTH)
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["thumbnail_url"].endswith("/small")


def test_explore_accepts_empty_root_path(client, monkeypatch, tmp_path):
    (tmp_path / "Album").mkdir()
    (tmp_path / "example.jpg").write_bytes(b"example")
    monkeypatch.setattr(api, "MEDIA_ROOT", tmp_path.resolve())

    response = client.get("/api/explore?path=", auth=AUTH)

    assert response.status_code == 200
    assert response.json() == {
        "path": "",
        "entries": [
            {
                "name": "Album",
                "path": "Album",
                "type": "directory",
                "media_url": None,
                "thumbnail_url": None,
                "size": None,
                "indexed": False,
            },
            {
                "name": "example.jpg",
                "path": "example.jpg",
                "type": "image",
                "media_url": "/media/example.jpg",
                "thumbnail_url": "/thumbnail/example.jpg/small",
                "size": 7,
                "indexed": False,
            },
        ],
    }


def test_index_tree_queues_durable_job(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api, "MEDIA_ROOT", tmp_path.resolve())

    response = client.post("/api/images/index-tree", auth=AUTH)

    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "pending"
    assert job["max_depth"] is None
    assert job["processed"] == 0

    status_response = client.get(f"/api/index-jobs/{job['id']}", auth=AUTH)
    assert status_response.status_code == 200
    assert status_response.json()["id"] == job["id"]

    cancel_response = client.post(f"/api/index-jobs/{job['id']}/cancel", auth=AUTH)
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"
