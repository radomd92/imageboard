FROM python:3.13.5-slim-bookworm AS runtime

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
COPY entrypoint.sh ./entrypoint.sh
RUN chmod 755 ./entrypoint.sh

USER imageboard
EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "runserver:app", "--worker-class=uvicorn.workers.UvicornWorker", "--bind=0.0.0.0:8000", "--workers=2", "--timeout=30", "--graceful-timeout=30", "--keep-alive=5", "--error-logfile=-"]
