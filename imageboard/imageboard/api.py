"""Authenticated JSON API for indexed media and its context."""

import hmac
import os
import unicodedata
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, unquote
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)
from werkzeug.security import check_password_hash

DATABASE_URL = os.environ.get(
    "IMAGEBOARD_DATABASE_URL", "postgresql+psycopg://imageboard:imageboard@database:5432/imageboard"
)
MEDIA_URL = os.environ.get("IMAGEBOARD_MEDIA_URL", "/media")
MEDIA_ROOT = Path(os.environ.get("IMAGEBOARD_MEDIA_ROOT", "/srv/media")).resolve()
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
security = HTTPBasic(auto_error=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    password: Mapped[str]
    registered: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    karma: Mapped[int] = mapped_column(default=0)
    privileges: Mapped[str] = mapped_column(default="user")
    banned: Mapped[bool] = mapped_column(default=False)


class TagImage(Base):
    __tablename__ = "tag_image"
    id: Mapped[int] = mapped_column(primary_key=True)
    image: Mapped[int] = mapped_column(index=True)
    tag: Mapped[int] = mapped_column(index=True)


class Tag(Base):
    __tablename__ = "tag"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


class Image(Base):
    __tablename__ = "image"
    id: Mapped[int] = mapped_column(primary_key=True)
    image_path: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    created_date: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    file_size: Mapped[int | None]
    hits: Mapped[int] = mapped_column(default=0)
    uploader: Mapped[int | None]


class Message(Base):
    __tablename__ = "message"
    id: Mapped[int] = mapped_column(primary_key=True)
    from_user: Mapped[int | None]
    image: Mapped[int]
    text: Mapped[str]
    reply_to: Mapped[int | None]
    message_date: Mapped[datetime]


class ImageHit(Base):
    __tablename__ = "image_hits"
    hit_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    image_id: Mapped[int]
    user_id: Mapped[int | None]
    hit_date: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    type: Mapped[str] = mapped_column(default="image")


class AuditEvent(Base):
    __tablename__ = "audit_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None]
    action: Mapped[str]
    object_type: Mapped[str]
    object_id: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))


class IndexJob(Base):
    __tablename__ = "index_job"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    root_path: Mapped[str] = mapped_column(default="")
    max_depth: Mapped[int | None]
    status: Mapped[str] = mapped_column(default="pending")
    requested_by: Mapped[int | None]
    worker_id: Mapped[str | None]
    lease_expires_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    discovered: Mapped[int] = mapped_column(default=0)
    processed: Mapped[int] = mapped_column(default=0)
    indexed: Mapped[int] = mapped_column(default=0)
    updated: Mapped[int] = mapped_column(default=0)
    deindexed: Mapped[int] = mapped_column(default=0)
    skipped: Mapped[int] = mapped_column(default=0)
    errors: Mapped[int] = mapped_column(default=0)
    error_code: Mapped[str | None]


class ContextUpdate(BaseModel):
    tags: list[str] | None = Field(default=None, max_length=50)
    comment: str | None = Field(default=None, max_length=500)


class MediaIndex(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class IndexJobCreate(BaseModel):
    path: str = Field(default="", max_length=4096)
    max_depth: int | None = Field(default=None, ge=0, le=128)


class ImageUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CommentCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    reply_to: int | None = None


def db_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def current_user(
    credentials: HTTPBasicCredentials | None = Depends(security), session: Session = Depends(db_session)
) -> User:
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Authentication required", {"WWW-Authenticate": "Basic"}
        )
    user = session.scalar(select(User).where(User.name == credentials.username))
    valid = user is not None and not user.banned and check_password_hash(user.password, credentials.password)
    if not valid:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid credentials", {"WWW-Authenticate": "Basic"}
        )
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.privileges != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return user


def canonical_path(value: str, allow_empty: bool = False) -> str:
    if not value and allow_empty:
        return ""
    parts = value.split("$")
    if not value or any(
        not part or part in {".", ".."} or "/" in part or "\\" in part or "\x00" in part for part in parts
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid media path")
    return "$".join(parts)


def media_file(path: str) -> tuple[Path, str]:
    canonical = canonical_path(path)
    target = (MEDIA_ROOT / Path(*canonical.split("$"))).resolve()
    try:
        target.relative_to(MEDIA_ROOT)
    except ValueError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid media path") from error
    if not target.is_file() or target.is_symlink():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media file not found")
    return target, canonical


def supported_media(path: str) -> bool:
    return path.rsplit(".", 1)[-1].lower() in {
        "avif", "avi", "bmp", "gif", "jpeg", "jpg", "m4v", "mov", "mp4", "png", "tif", "tiff", "webm", "webp", "wmv"
    }


def media_kind(path: str) -> str:
    return "video" if path.rsplit(".", 1)[-1].lower() in {"avi", "m4v", "mov", "mp4", "webm", "wmv"} else "image"


def record_event(session: Session, user: User, action: str, object_id: int | str) -> None:
    session.add(
        AuditEvent(
            actor_id=user.id,
            action=action,
            object_type="image",
            object_id=str(object_id),
            created_at=datetime.now(timezone.utc),
        )
    )


def index_job_payload(job: IndexJob) -> dict:
    return {
        "id": str(job.id),
        "status": job.status,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "max_depth": job.max_depth,
        "discovered": job.discovered,
        "processed": job.processed,
        "indexed": job.indexed,
        "updated": job.updated,
        "deindexed": job.deindexed,
        "skipped": job.skipped,
        "errors": job.errors,
        "error_code": job.error_code,
    }


def enqueue_index_job(session: Session, user: User, path: str, max_depth: int | None) -> IndexJob:
    canonical = canonical_path(path, allow_empty=True) if path else ""
    active = session.scalar(
        select(IndexJob).where(IndexJob.status.in_(("pending", "running"))).order_by(IndexJob.created_at)
    )
    if active is not None:
        return active
    job = IndexJob(root_path=canonical, max_depth=max_depth, requested_by=user.id)
    session.add(job)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        active = session.scalar(
            select(IndexJob).where(IndexJob.status.in_(("pending", "running"))).order_by(IndexJob.created_at)
        )
        if active is None:
            raise
        return active
    session.refresh(job)
    return job


def clean_tag(value: str) -> str:
    value = " ".join(value.strip().lower().split())
    if (
        not value
        or len(value) > 100
        or "/" in value
        or "\\" in value
        or any(unicodedata.category(char).startswith("C") for char in value)
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid tag")
    return value


def image_payload(session: Session, image: Image) -> dict:
    tag_ids = session.scalars(select(TagImage.tag).where(TagImage.image == image.id)).all()
    tags = (
        session.scalars(select(Tag.name).where(Tag.id.in_(tag_ids)).order_by(Tag.name)).all()
        if tag_ids
        else []
    )
    comments = session.execute(
        select(Message, User.name)
        .outerjoin(User, User.id == Message.from_user)
        .where(Message.image == image.id)
        .order_by(Message.message_date, Message.id)
    ).all()
    media_path = "/".join(quote(part, safe="") for part in image.image_path.split("$"))
    uploader = session.scalar(select(User.name).where(User.id == image.uploader)) if image.uploader else None
    kind = media_kind(image.image_path)
    return {
        "id": image.id,
        "name": image.name,
        "path": image.image_path,
        "media_url": f"{MEDIA_URL.rstrip('/')}/{media_path}",
        "file_url": f"/api/images/{image.id}/file",
        "thumbnail_url": f"/thumbnail/{media_path}/small" if kind == "image" else f"{MEDIA_URL.rstrip('/')}/{media_path}",
        "kind": kind,
        "created_at": image.created_date,
        "file_size": image.file_size,
        "hits": image.hits,
        "uploader": uploader,
        "tags": list(tags),
        "comments": [
            {
                "id": row.Message.id,
                "author": row.name,
                "text": row.Message.text,
                "created_at": row.Message.message_date,
                "reply_to": row.Message.reply_to,
            }
            for row in comments
        ],
    }


app = FastAPI(title="Paradise Imageboard", version="2.0")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update(
        {
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        }
    )
    if response.media_type == "text/html":
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "script-src 'self'; style-src 'self'; img-src 'self'; "
            "media-src 'self'; connect-src 'self'"
        )
    return response


@app.get("/health/live")
def live() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=FileResponse)
def index(_: User = Depends(current_user)) -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/health/ready")
def ready(request: Request, session: Session = Depends(db_session)) -> dict:
    expected = os.environ.get("IMAGEBOARD_HEALTH_TOKEN", "")
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    session.execute(select(1))
    return {"status": "ok"}


@app.get("/api/internal/authorize", status_code=status.HTTP_204_NO_CONTENT)
def authorize(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> None:
    original = unquote(request.headers.get("X-Original-URI", "")).split("?", 1)[0]
    if original.startswith("/media/"):
        path = original.removeprefix("/media/").replace("/", "$")
    elif original.startswith("/thumbnail/"):
        path = original.removeprefix("/thumbnail/").rsplit("/", 1)[0].replace("/", "$")
    else:
        return None
    if user.privileges != "admin" and session.scalar(
        select(Image.id).where(Image.image_path == path)
    ) is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Media is not indexed")
    return None


@app.get("/api/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"id": user.id, "name": user.name, "admin": user.privileges == "admin"}


@app.get("/api/images")
def list_images(
    q: str = Query(default="", max_length=100),
    tag: str = Query(default="", max_length=100),
    untagged: bool = False,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=30, ge=1, le=100),
    _: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> dict:
    query = select(Image)
    if q:
        pattern = f"%{q.strip().lower()}%"
        query = query.where(
            or_(func.lower(Image.name).like(pattern), func.lower(Image.image_path).like(pattern))
        )
    if tag:
        query = query.join(TagImage, TagImage.image == Image.id).join(Tag, Tag.id == TagImage.tag).where(
            func.lower(Tag.name) == tag.strip().lower()
        )
    if untagged:
        query = query.where(~select(TagImage.id).where(TagImage.image == Image.id).exists())
    count_query = select(func.count()).select_from(query.order_by(None).subquery())
    total = session.scalar(count_query) or 0
    images = session.scalars(
        query.order_by(Image.created_date.desc(), Image.id.desc()).offset((page - 1) * limit).limit(limit)
    ).all()
    return {"items": [image_payload(session, image) for image in images], "page": page, "limit": limit, "total": total}


@app.get("/api/tags")
def list_tags(_: User = Depends(current_user), session: Session = Depends(db_session)) -> list[dict]:
    rows = session.execute(
        select(Tag.name, func.count(TagImage.image), func.max(TagImage.image))
        .join(TagImage, TagImage.tag == Tag.id)
        .group_by(Tag.id, Tag.name)
        .order_by(func.count(TagImage.image).desc(), Tag.name)
    ).all()
    return [{"name": name, "count": count, "image_id": image_id} for name, count, image_id in rows]


@app.get("/api/dashboard")
def dashboard(_: User = Depends(current_user), session: Session = Depends(db_session)) -> dict:
    total = session.scalar(select(func.count(Image.id))) or 0
    untagged = session.scalar(
        select(func.count(Image.id)).where(~select(TagImage.id).where(TagImage.image == Image.id).exists())
    ) or 0
    month_start = datetime.now(timezone.utc) - timedelta(days=30)
    popular = session.execute(
        select(Tag.name, func.count(ImageHit.hit_id))
        .join(TagImage, TagImage.tag == Tag.id)
        .join(ImageHit, ImageHit.image_id == TagImage.image)
        .where(ImageHit.hit_date >= month_start)
        .group_by(Tag.id, Tag.name)
        .order_by(func.count(ImageHit.hit_id).desc())
        .limit(8)
    ).all()
    return {
        "total": total,
        "untagged": untagged,
        "popular_tags": [{"name": name, "hits": hits} for name, hits in popular],
    }


@app.get("/api/explore")
def explore(
    path: str = Query(default="", max_length=4096),
    _: User = Depends(require_admin),
    session: Session = Depends(db_session),
) -> dict:
    canonical = canonical_path(path, allow_empty=True) if path else ""
    directory = (MEDIA_ROOT / Path(*canonical.split("$"))).resolve()
    try:
        directory.relative_to(MEDIA_ROOT)
    except ValueError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid directory path") from error
    if not directory.is_dir() or directory.is_symlink():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Directory not found")
    try:
        items = list(directory.iterdir())
    except PermissionError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Directory is not readable") from error
    except OSError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Directory is not available") from error

    entries = []
    for item in items:
        try:
            is_directory = item.is_dir()
            is_file = item.is_file()
            if item.is_symlink() or "$" in item.name or any(
                unicodedata.category(char).startswith("C") for char in item.name
            ):
                continue
            if not is_directory and not supported_media(item.name):
                continue
            item_path = "$".join(filter(None, [canonical, item.name]))
            encoded_path = "/".join(quote(part, safe="") for part in item_path.split("$"))
            kind = "directory" if is_directory else media_kind(item.name)
            entries.append({
                "name": item.name,
                "path": item_path,
                "type": kind,
                "media_url": None if is_directory else f"{MEDIA_URL.rstrip('/')}/{encoded_path}",
                "thumbnail_url": f"/thumbnail/{encoded_path}/small" if kind == "image" else None,
                "size": item.stat().st_size if is_file else None,
                "indexed": session.scalar(select(Image.id).where(Image.image_path == item_path)) is not None,
            })
        except OSError:
            # Mount contents can change while being enumerated; omit unstable entries.
            continue
    entries.sort(key=lambda entry: (entry["type"] != "directory", entry["name"].lower()))
    return {"path": canonical, "entries": entries}


@app.post("/api/images/index", status_code=status.HTTP_202_ACCEPTED)
def index_media(
    payload: MediaIndex, user: User = Depends(require_admin), session: Session = Depends(db_session)
) -> dict:
    return index_job_payload(enqueue_index_job(session, user, payload.path, 0))


@app.post("/api/images/index-tree", status_code=status.HTTP_202_ACCEPTED)
def index_media_tree(
    user: User = Depends(require_admin), session: Session = Depends(db_session)
) -> dict:
    return index_job_payload(enqueue_index_job(session, user, "", None))


@app.post("/api/index-jobs", status_code=status.HTTP_202_ACCEPTED)
def create_index_job(
    payload: IndexJobCreate,
    user: User = Depends(require_admin),
    session: Session = Depends(db_session),
) -> dict:
    return index_job_payload(enqueue_index_job(session, user, payload.path, payload.max_depth))


@app.get("/api/index-jobs/{job_id}")
def get_index_job(
    job_id: UUID, _: User = Depends(require_admin), session: Session = Depends(db_session)
) -> dict:
    job = session.get(IndexJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Index job not found")
    return index_job_payload(job)


@app.post("/api/index-jobs/{job_id}/cancel")
def cancel_index_job(
    job_id: UUID, _: User = Depends(require_admin), session: Session = Depends(db_session)
) -> dict:
    job = session.get(IndexJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Index job not found")
    if job.status in {"pending", "running"}:
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        session.commit()
    return index_job_payload(job)


@app.get("/api/images/{image_id}")
def get_image(image_id: int, _: User = Depends(current_user), session: Session = Depends(db_session)) -> dict:
    image = session.get(Image, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    return image_payload(session, image)


@app.get("/api/images/{image_id}/file")
def get_image_file(
    image_id: int, _: User = Depends(current_user), session: Session = Depends(db_session)
) -> RedirectResponse:
    image = session.get(Image, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    try:
        media_file(image.image_path)
    except HTTPException as error:
        if error.status_code == status.HTTP_404_NOT_FOUND:
            enqueue_index_job(session, _, image.image_path, 0)
        raise
    image.hits += 1
    session.add(ImageHit(image_id=image.id, user_id=_.id, type="image"))
    session.commit()
    path = "/".join(quote(part, safe="") for part in canonical_path(image.image_path).split("$"))
    return RedirectResponse(f"{MEDIA_URL.rstrip('/')}/{path}", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.post("/api/images/{image_id}/context")
def add_context(
    image_id: int,
    update: ContextUpdate,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> dict:
    image = session.get(Image, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    if update.tags is None and update.comment is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Supply tags or comment")
    if update.tags is not None:
        if user.privileges != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required to edit tags")
        names = list(dict.fromkeys(clean_tag(tag) for tag in update.tags))
        session.query(TagImage).filter(TagImage.image == image.id).delete()
        for name in names:
            tag = session.scalar(select(Tag).where(Tag.name == name))
            if tag is None:
                tag = Tag(name=name)
                session.add(tag)
                session.flush()
            session.add(TagImage(image=image.id, tag=tag.id))
        record_event(session, user, "edit_tags", image.id)
    if update.comment is not None:
        text = update.comment.strip()
        if not text or any(unicodedata.category(char).startswith("C") for char in text):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid comment")
        session.add(
            Message(
                from_user=user.id,
                image=image.id,
                text=text,
                reply_to=None,
                message_date=datetime.now(timezone.utc),
            )
        )
    session.commit()
    return image_payload(session, image)


@app.patch("/api/images/{image_id}")
def update_image(
    image_id: int,
    update: ImageUpdate,
    user: User = Depends(require_admin),
    session: Session = Depends(db_session),
) -> dict:
    image = session.get(Image, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    name = " ".join(update.name.strip().split())
    if any(unicodedata.category(char).startswith("C") for char in name):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid title")
    image.name = name
    record_event(session, user, "edit_title", image.id)
    session.commit()
    return image_payload(session, image)


@app.post("/api/images/{image_id}/comments")
def add_comment(
    image_id: int,
    comment: CommentCreate,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
) -> dict:
    image = session.get(Image, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    text = comment.text.strip()
    if not text or any(unicodedata.category(char).startswith("C") for char in text):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid comment")
    if comment.reply_to is not None:
        parent = session.scalar(
            select(Message).where(Message.id == comment.reply_to, Message.image == image.id)
        )
        if parent is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid reply target")
        depth = 1
        while parent.reply_to is not None:
            depth += 1
            if depth >= 8:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Reply depth exceeded")
            parent = session.get(Message, parent.reply_to)
            if parent is None or parent.image != image.id:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid comment thread")
    session.add(
        Message(
            from_user=user.id,
            image=image.id,
            text=text,
            reply_to=comment.reply_to,
            message_date=datetime.now(timezone.utc),
        )
    )
    record_event(session, user, "comment", image.id)
    session.commit()
    return image_payload(session, image)
