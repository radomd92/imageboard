# Paradise Imageboard

Private Go media catalog. PostgreSQL stores image metadata, tags, comments, users, and AES-256-GCM encrypted generated thumbnails. Nginx directly serves mounted read-only media; Go generates thumbnails and stores only encrypted blobs in PostgreSQL. PostgreSQL and the application run as separate Compose projects so application redeployments cannot replace or remove the database service. A separate Go worker indexes media asynchronously through PostgreSQL-backed durable jobs. Python is retained only for Alembic migrations and local account administration; it serves no HTTP API.

## Deploy

1. Copy `.env.example` to `.env`; set strong database password, health token, media mount path, and TLS certificate paths.
2. Provision the persistent volume and shared network once, then start the independent PostgreSQL deployment.

   ```bash
   docker volume create imageboard_postgres-data
   docker network create imageboard-backend
   docker compose -p imageboard-database -f docker-compose.database.yml up -d
   ```

3. After PostgreSQL is healthy, build and start the application deployment. The one-shot `migrator` service applies Alembic migrations before the Go API and Go index worker start.

   ```bash
   docker compose up -d --build
   ```

4. Create first administrator. Additional accounts can be created in the admin-only Users dashboard.

   ```bash
   docker compose run --rm --entrypoint python migrator -m imageboard.create_user administrator --admin
   ```

5. Read the generated v3 onion address after Tor reaches healthy state.

   ```bash
   docker compose exec tor cat /var/lib/tor/imageboard/hostname
   ```

Media stays outside containers. `IMAGEBOARD_MEDIA_ROOT=/srv/photos` mounts host `/srv/photos` read-only at Nginx `/srv/media`; Nginx serves it at `https://host:8443/media/...`.

## Async indexing

The Go `index-worker` service claims durable jobs from PostgreSQL. Index requests return immediately and never hold a browser or Nginx connection while scanning. Jobs traverse from the requested root, batch metadata upserts, and report progress through the API. A successful scan reconciles its scope: indexed files absent from the scanned folder are de-indexed asynchronously. Incomplete scans caused by unreadable or unstable filesystem entries never de-index records.

Start a full recursive index job with the included helper. It prompts for credentials unless supplied through environment variables; do not put credentials in the script.

```bash
INDEX_INSECURE=1 python3 index_all.py
```

`INDEX_INSECURE=1` is needed only for a self-signed local TLS certificate. Set `INDEX_API_URL` for another endpoint, and `IMAGEBOARD_USER` / `IMAGEBOARD_PASSWORD` for non-interactive use. The Tor endpoint remains read-only and cannot submit jobs.

## Local image descriptions

`describe_image.py` downloads one HTTP(S) image and sends it to a loopback-only vision model endpoint. It uses only the Python standard library and prints JSON with a concise description and normalized catalog-ready tags.

```bash
python3 describe_image.py 'https://example.invalid/image.jpg' --model gemma3
python3 describe_image.py 'https://example.invalid/image.jpg' --api openai --model gemma3 --endpoint http://127.0.0.1:11434/v1/chat/completions
python3 describe_image.py --untagged --imageboard-url https://127.0.0.1:8443 --model gemma3
```

The default is Ollama at `http://127.0.0.1:11434/api/generate`. `--untagged` paginates all untagged image records through `/api/images?untagged=true`, prompts for Imageboard HTTP Basic credentials, and downloads each returned protected media URL only while the script runs. It prints the image ID, description, and suggested tags. Use `--apply` to replace each image's tags, and add `--comment-description` only when comments should be created too.

The script rejects model endpoints that resolve outside loopback addresses, caps downloads at 20 MiB, and never prints source URLs, credentials, or image bytes.

## Password Rotation

Rotate an HTTP Basic password without exposing it in command arguments or environment variables:

```bash
./rotate_password.sh
```

The optional first argument selects another username. The script updates the Werkzeug-compatible scrypt hash. The API rechecks current account state on each request, so the old password stops working without restarting the application.

## Users and profiles

Browser-native HTTP Basic authentication remains the login screen. Administrators use **Users** to search accounts, create users, reset passwords, set administrator status, and disable/reactivate accounts. Passwords contain 14–256 characters without control characters and are stored only as randomly salted scrypt hashes. Usernames contain 3–100 characters, with no colon, control characters, or surrounding whitespace. Usernames are case-sensitive and fixed after creation.

Disabling preserves comments and profiles but rejects subsequent authentication. The last active administrator cannot be disabled or demoted. Legacy accounts with disabled password placeholders need a password reset before reactivation. Account changes are audited without storing passwords or hashes in audit events.

Click your sidebar username to see your profile and change your password using your current password. After changing your own password, use **Sign In Again** to reload the protected page; if the browser continues sending old credentials, close the authenticated browser session and reopen the site. Browsers manage Basic credentials themselves; the application does not persist them in browser storage.

Comment usernames link to authenticated user profiles with newest-first, paginated comment/reply history across media pages. **View thread** opens the original media and highlights the comment. Profile hash URLs can be bookmarked and reloaded. Other members cannot access account administration or change another user's password.

## PostgreSQL lifecycle

Application commands such as `docker compose down` and `docker compose up -d --build` do not manage PostgreSQL. Database data remains in the external `imageboard_postgres-data` volume across container replacement and application redeployments. Compose does not delete this external volume, including when `down --volumes` is used.

Manage PostgreSQL separately:

```bash
docker compose -p imageboard-database -f docker-compose.database.yml ps
docker compose -p imageboard-database -f docker-compose.database.yml pull
docker compose -p imageboard-database -f docker-compose.database.yml up -d
```

Delete `imageboard_postgres-data` only when permanent data deletion is intended. Persistent volumes are not backups; take regular logical backups outside the repository:

```bash
./backup_database.sh /path/to/secure-backups
```

The script creates a UTC-timestamped `.tar.bz2` archive containing a plain SQL dump with owner-only permissions. Restore with `tar -xOjf backup.tar.bz2 | psql -U imageboard -d imageboard` in a compatible PostgreSQL container.

## Tor hidden service

The `tor` service publishes Nginx's internal HTTP-only port as onion port 80. The onion protocol already authenticates and encrypts traffic end to end, so TLS is intentionally omitted on this path. Port 8080 listens only on loopback inside the network namespace shared by Nginx and Tor; it is not reachable from the host or other containers.

HTTP Basic authentication remains required. The onion media catalog is read-only: Nginx permits authenticated `GET`/`HEAD` requests, rejects media mutation methods, and blocks the nominally read-only file endpoint because it records view-count changes. Media and thumbnails remain authenticated. The onion UI hides media editing, commenting, and indexing controls.

Account management is available on Tor: Nginx permits `PUT /api/me/password`, `POST /api/admin/users`, `PATCH /api/admin/users/{id}`, and `PUT /api/admin/users/{id}/password`. Administrator authorization is enforced by Go on every admin endpoint. Account writes require JSON and `X-Imageboard-Request: account`; cross-origin browser requests are rejected. Onion transport encrypts these requests end to end through Tor.

The onion identity and private keys live in the `tor-data` volume. Preserve that volume to keep the address stable, protect its contents as credentials, and never commit exported keys. Removing the volume creates a new onion address on next start.

## API

All `/api` and `/media` requests require HTTP Basic authentication. Use TLS for direct access, or Tor-encrypted transport for the onion endpoint as described above.

`POST /api/images/{id}/context` accepts JSON bodies up to 8 KiB (8,192 bytes), including tags and comments for context enrichment. Individual comment length and tag length/count limits still apply.

```bash
curl --user user:password https://host:8443/api/images/42
curl --user user:password -L https://host:8443/api/images/42/file -o image
curl --user user:password -X POST https://host:8443/api/images/42/context \
  -H 'content-type: application/json' \
  -d '{"tags":["travel","sunset"],"comment":"Taken at dusk"}'
```

`GET /api/images/{id}` returns image metadata, tags, comments, and direct media URL. `GET /api/images/{id}/file` increments view count then redirects to protected Nginx media. `POST /api/images/{id}/context` replaces tags when `tags` supplied and appends comment when `comment` supplied.

Account endpoints:

| Endpoint | Access | Body/query |
| --- | --- | --- |
| `GET /api/admin/users` | Admin | `q`, `page`, `limit` (maximum 100) |
| `POST /api/admin/users` | Admin | `name`, `password`, `admin` |
| `PATCH /api/admin/users/{id}` | Admin | `admin` and/or `disabled` |
| `PUT /api/admin/users/{id}/password` | Admin | `password` |
| `PUT /api/me/password` | Authenticated | `current_password`, `password` |
| `GET /api/users/{id}` | Authenticated | Username, registration date, comment count |
| `GET /api/users/{id}/comments` | Authenticated | `cursor`, `limit` (maximum 100); response includes `next_cursor` |

Account writes require `Content-Type: application/json` and `X-Imageboard-Request: account`, with an 8 KiB request limit. Responses never include password hashes. Comment responses include nullable `author_id`; history includes `image_id` and `image_name`.

For account integration tests, migrate a disposable PostgreSQL database to head, then run `go test -race ./...` from `go_api` with `IMAGEBOARD_TEST_DATABASE_URL` set to its connection URL. Tests create and remove an isolated schema cloned from the migrated tables. CI runs these checks against a dedicated PostgreSQL service.

Nginx restricts mutation methods by endpoint, hides directory indexes, disables symlinks, authenticates each media request through the Go API, restricts TLS, rate-limits, and applies security headers. Video thumbnails remain disabled; the Go thumbnail cache generates image previews only.
