FROM python:3.14.0-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system --gid 10001 imageboard \
    && useradd --system --uid 10001 --gid imageboard --home-dir /app imageboard

WORKDIR /app
COPY requirements.txt ./
RUN pip install --requirement requirements.txt

COPY imageboard ./imageboard
COPY migrations ./migrations
COPY runserver.py ./

USER imageboard
EXPOSE 8000

CMD ["gunicorn", "--bind=0.0.0.0:8000", "--workers=2", "--threads=4", "--timeout=30", "--graceful-timeout=30", "--keep-alive=5", "--access-logfile=-", "--error-logfile=-", "runserver:app"]
