#!/usr/bin/env bash
# Create a compressed PostgreSQL SQL archive without exposing database credentials.
set -euo pipefail

if [[ $# -ne 1 ]]; then
    printf 'Usage: %s BACKUP_DIRECTORY\n' "$0" >&2
    exit 2
fi

backup_directory="$1"
if [[ ! -d "$backup_directory" ]]; then
    printf 'Backup directory does not exist: %s\n' "$backup_directory" >&2
    exit 1
fi

if [[ ! -w "$backup_directory" ]]; then
    printf 'Backup directory is not writable: %s\n' "$backup_directory" >&2
    exit 1
fi

repository_root="$(cd -- "$(dirname -- "$0")" && pwd)"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
dump_name="imageboard-${timestamp}.sql"
backup_path="${backup_directory%/}/imageboard-${timestamp}.tar.bz2"
temporary_dump_path="${backup_directory%/}/${dump_name}"
temporary_archive_path="${backup_path}.tmp"

if [[ -e "$backup_path" || -e "$temporary_dump_path" || -e "$temporary_archive_path" ]]; then
    printf 'Backup path already exists: %s\n' "$backup_path" >&2
    exit 1
fi

umask 077
trap 'rm -f -- "$temporary_dump_path" "$temporary_archive_path"' EXIT

docker compose --project-directory "$repository_root" -p imageboard-database \
    -f "$repository_root/docker-compose.database.yml" exec -T database \
    pg_dump -U imageboard -d imageboard > "$temporary_dump_path"

tar -cjf "$temporary_archive_path" -C "$backup_directory" "${temporary_dump_path##*/}"
mv -- "$temporary_archive_path" "$backup_path"
trap - EXIT
rm -- "$temporary_dump_path"
printf 'Database backup written to %s\n' "$backup_path"
