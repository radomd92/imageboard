# Paradise Imageboard

Paradise is a private, self-hosted media catalog. Nginx serves an existing read-only image/video tree, while Flask stores searchable metadata, tags, authenticated comments, audit events, and view counts in PostgreSQL.

The service is private by default. All application content requires a local account. Only administrators can browse the media origin, index files, or edit metadata. Public registration is intentionally unavailable.

## Security Model

- Flask is the only browser-facing application. Do not expose the media-origin Nginx service publicly.
- The media origin must use HTTPS with a trusted private or public CA. TLS verification cannot be disabled.
- Every media request must reference an already indexed canonical path and an allow-listed media extension/MIME type.
- Media is streamed with time and size limits. The application does not deserialize or persist upstream media cache payloads.
- Mutating requests require authentication and CSRF tokens. Metadata changes require administrator privileges.
- Login, comments, media, thumbnails, exploration, and indexing are rate limited.
- Sessions use secure, HTTP-only, SameSite cookies. Host allow-listing, CSP, HSTS, anti-framing, MIME-sniffing, referrer, and permissions headers are enabled.
- Privileged changes and comments create database audit events.

This design materially reduces common application risks, but no software is "bulletproof." Host patching, firewall policy, TLS key custody, database/media backups, monitoring, and incident response remain operator responsibilities.

## Requirements

- Python 3.13 or Docker
- PostgreSQL 17
- Redis 8 for shared production rate limits
- Nginx compiled with `ngx_http_image_filter_module`
- A trusted TLS certificate for both the user-facing reverse proxy and media origin

## Configuration

Copy `.env.example` to `.env` and replace every placeholder. Never commit `.env`.

Generate the application secret with:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Important settings:

- `IMAGEBOARD_SECRET_KEY`: at least 32 random characters
- `IMAGEBOARD_DATABASE_URL`: SQLAlchemy PostgreSQL connection URL
- `IMAGEBOARD_FILE_SERVER`: HTTPS URL to the Nginx `/images` location, without embedded credentials
- `IMAGEBOARD_FILE_SERVER_USERNAME` and `IMAGEBOARD_FILE_SERVER_PASSWORD`: media-origin Basic Auth
- `IMAGEBOARD_FILE_SERVER_CA_BUNDLE`: CA bundle path, or omit it for system trust
- `IMAGEBOARD_TRUSTED_HOSTS`: comma-separated browser-facing hostnames
- `IMAGEBOARD_TRUSTED_PROXY_NETWORKS`: exact proxy source CIDRs permitted to supply `X-Forwarded-For`
- `IMAGEBOARD_HEALTH_TOKEN`: independent random bearer token for `/health/ready`
- `IMAGEBOARD_RATE_LIMIT_STORAGE`: Redis URL in multi-worker production

Secure cookies and HSTS default to enabled. They may only be disabled for local HTTP development, never production.

## Database Setup

Install dependencies and apply migrations from `imageboard/`:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
flask --app runserver:app db upgrade
flask --app runserver:app create-user --admin
```

For an existing PostgreSQL installation, take a verified database backup before migrating. The baseline detects the legacy tables, preserves valid media metadata, tags, comments, ratings, and hits, and adds the hardened constraints and audit table. All legacy account names are renamed and all passwords are deliberately invalidated because the old application never enforced authentication. Create new accounts with the CLI. Test the migration against a restored staging copy and verify row counts, application behavior, and rollback procedures before production cutover. The baseline migration is intentionally irreversible; rollback means restoring the verified backup.

## Production Deployment

`docker-compose.yml` provides the application, PostgreSQL, and Redis baseline. The application binds only to `127.0.0.1:8000`; place a maintained HTTPS reverse proxy in front of it.

```bash
docker compose build
docker compose run --rm app flask --app runserver:app db upgrade
docker compose run --rm app flask --app runserver:app create-user --admin
docker compose up -d
```

Deployment requirements:

- Restrict media-origin port `8443` to the application host at the firewall.
- Mount CA certificates and credentials through secrets, not container images or environment files where a secrets manager is available.
- Terminate browser TLS at the reverse proxy and forward the original `Host` unchanged.
- Do not add `ProxyFix` unless exact trusted proxy hops are configured.
- Back up PostgreSQL and the external media tree independently; regularly test restores.
- Alert on HTTP 401/403/429/5xx rates, readiness failures, origin TLS failures, storage capacity, and database health.
- Rotate application secrets, origin credentials, TLS keys, and user passwords under a documented incident procedure.

Liveness is available at `/health/live`. Readiness, including a database check, is available at `/health/ready` and requires `Authorization: Bearer <IMAGEBOARD_HEALTH_TOKEN>`.

## Media Origin

Adapt `nginx_file_server/nginx.conf.example`:

1. Serve a dedicated read-only media root with symlinks disabled.
2. Configure a valid TLS certificate and Basic Auth secret.
3. Restrict network access to the application host.
4. Keep all methods except `GET` denied.
5. Confirm image-filter memory limits fit the host.
6. Enable video thumbnail extraction only after independently reviewing and patching that third-party module.

## Verification

Install development dependencies and run:

```bash
pytest
ruff check imageboard tests
bandit -r imageboard -x imageboard/static
pip-audit -r requirements.txt
```

Dependency scanning is time-sensitive. Rebuild and rerun it whenever images or packages are updated.
