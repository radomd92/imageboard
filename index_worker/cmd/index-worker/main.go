package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unicode"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	defaultBatchSize = 500
	leaseDuration    = time.Minute
	pollInterval     = 2 * time.Second
)

type job struct {
	id          string
	rootPath    string
	maxDepth    *int
	requestedBy *int32
}

type mediaFile struct {
	path string
	name string
	size int64
}

type counters struct {
	discovered int64
	processed  int64
	indexed    int64
	updated    int64
	skipped    int64
	errors     int64
	deindexed  int64
}

type worker struct {
	pool      *pgxpool.Pool
	mediaRoot string
	batchSize int
	workerID  string
	log       *slog.Logger
}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	databaseURL := normalizeDatabaseURL(requiredEnv("IMAGEBOARD_DATABASE_URL"))
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		fatal("database connection setup failed", err)
	}
	defer pool.Close()
	if err := pool.Ping(ctx); err != nil {
		fatal("database unavailable", err)
	}

	w := worker{
		pool:      pool,
		mediaRoot: requiredEnv("IMAGEBOARD_MEDIA_ROOT"),
		batchSize: envInt("INDEX_BATCH_SIZE", defaultBatchSize),
		workerID:  workerIdentity(),
		log:       slog.New(slog.NewJSONHandler(os.Stdout, nil)),
	}
	w.log.Info("index worker started")
	w.run(ctx)
}

func (w *worker) run(ctx context.Context) {
	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()
	for {
		if err := ctx.Err(); err != nil {
			w.log.Info("index worker stopped")
			return
		}
		job, err := w.claim(ctx)
		if err != nil {
			w.log.Error("job claim failed", "error", err)
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
			}
			continue
		}
		if job == nil {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
			}
			continue
		}
		w.process(ctx, *job)
	}
}

func (w *worker) claim(ctx context.Context) (*job, error) {
	row := w.pool.QueryRow(ctx, `
WITH candidate AS (
    SELECT id
    FROM index_job
    WHERE status = 'pending' OR (status = 'running' AND lease_expires_at < NOW())
    ORDER BY created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE index_job job
SET status = 'running', worker_id = $1, lease_expires_at = NOW() + $2::interval,
    started_at = COALESCE(started_at, NOW()), finished_at = NULL, error_code = NULL,
    discovered = 0, processed = 0, indexed = 0, updated = 0, deindexed = 0, skipped = 0, errors = 0
FROM candidate
WHERE job.id = candidate.id
RETURNING job.id::text, job.root_path, job.max_depth, job.requested_by`, w.workerID, interval(leaseDuration))

	var claimed job
	if err := row.Scan(&claimed.id, &claimed.rootPath, &claimed.maxDepth, &claimed.requestedBy); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return &claimed, nil
}

func (w *worker) process(ctx context.Context, job job) {
	root, components, err := w.jobRoot(job.rootPath)
	if err != nil {
		w.finish(ctx, job, "failed", "invalid_root", counters{})
		return
	}

	info, err := os.Lstat(root)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) && job.rootPath != "" {
			count, deleteErr := w.deindexMissingScope(ctx, job)
			if deleteErr != nil {
				w.finish(ctx, job, "failed", "database_error", counters{})
				return
			}
			w.finish(ctx, job, "succeeded", "", counters{deindexed: count})
			return
		}
		w.finish(ctx, job, "failed", "media_root_unavailable", counters{errors: 1})
		return
	}
	if info.Mode()&os.ModeSymlink != 0 {
		w.finish(ctx, job, "failed", "invalid_root", counters{})
		return
	}

	var files []mediaFile
	counts := counters{}
	complete := true
	flush := func() bool {
		if len(files) == 0 {
			return true
		}
		if err := w.upsertBatch(ctx, job, files, &counts); err != nil {
			w.finish(ctx, job, "failed", "database_error", counts)
			return false
		}
		files = files[:0]
		return w.progress(ctx, job, counts)
	}

	if info.IsDir() {
		err = filepath.WalkDir(root, func(path string, entry fs.DirEntry, walkErr error) error {
			if walkErr != nil {
				counts.errors++
				complete = false
				if entry != nil && entry.IsDir() {
					return filepath.SkipDir
				}
				return nil
			}
			if path == root {
				return nil
			}
			rel, relErr := filepath.Rel(root, path)
			if relErr != nil {
				counts.errors++
				complete = false
				return nil
			}
			parts := append(append([]string{}, components...), strings.Split(rel, string(filepath.Separator))...)
			if !safeParts(parts) || entry.Type()&os.ModeSymlink != 0 {
				if entry.IsDir() {
					return filepath.SkipDir
				}
				return nil
			}
			depth := len(parts) - len(components) - 1
			if entry.IsDir() {
				if job.maxDepth != nil && depth >= *job.maxDepth {
					return filepath.SkipDir
				}
				return nil
			}
			if !entry.Type().IsRegular() || !supportedMedia(entry.Name()) {
				return nil
			}
			fileInfo, statErr := entry.Info()
			if statErr != nil {
				counts.errors++
				complete = false
				return nil
			}
			counts.discovered++
			files = append(files, mediaFile{path: strings.Join(parts, "$"), name: entry.Name(), size: fileInfo.Size()})
			if len(files) >= w.batchSize && !flush() {
				return errStop
			}
			return nil
		})
	} else if info.Mode().IsRegular() && supportedMedia(filepath.Base(root)) {
		counts.discovered = 1
		files = append(files, mediaFile{path: job.rootPath, name: filepath.Base(root), size: info.Size()})
	} else {
		complete = false
		counts.errors++
	}
	if err != nil && !errors.Is(err, errStop) {
		complete = false
		counts.errors++
	}
	if errors.Is(err, errStop) || !flush() {
		return
	}
	if w.cancelled(ctx, job) {
		w.finish(ctx, job, "cancelled", "", counts)
		return
	}
	// A depth-limited directory scan cannot authoritatively reconcile descendants.
	if complete && job.maxDepth == nil {
		deindexed, deleteErr := w.deindexStale(ctx, job)
		if deleteErr != nil {
			w.finish(ctx, job, "failed", "database_error", counts)
			return
		}
		counts.deindexed = deindexed
	}
	w.finish(ctx, job, "succeeded", "", counts)
}

var errStop = errors.New("stop scan")

func (w *worker) upsertBatch(ctx context.Context, job job, files []mediaFile, counts *counters) error {
	paths := make([]string, len(files))
	names := make([]string, len(files))
	sizes := make([]int64, len(files))
	for i, file := range files {
		paths[i], names[i], sizes[i] = file.path, file.name, file.size
	}
	tx, err := w.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	rows, err := tx.Query(ctx, "SELECT image_path, file_size FROM image WHERE image_path = ANY($1)", paths)
	if err != nil {
		return err
	}
	existing := map[string]*int64{}
	for rows.Next() {
		var path string
		var size *int64
		if err := rows.Scan(&path, &size); err != nil {
			rows.Close()
			return err
		}
		existing[path] = size
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return err
	}
	rows.Close()
	for _, file := range files {
		old, found := existing[file.path]
		switch {
		case !found:
			counts.indexed++
		case old == nil || *old != file.size:
			counts.updated++
		default:
			counts.skipped++
		}
	}
	_, err = tx.Exec(ctx, `
INSERT INTO image (image_path, name, file_size, hits, uploader, last_index_job)
SELECT path, name, size, 0, $4, $5::uuid
FROM UNNEST($1::text[], $2::text[], $3::bigint[]) AS source(path, name, size)
ON CONFLICT (image_path) DO UPDATE
SET file_size = EXCLUDED.file_size, last_index_job = EXCLUDED.last_index_job`, paths, names, sizes, job.requestedBy, job.id)
	if err != nil {
		return err
	}
	counts.processed += int64(len(files))
	return tx.Commit(ctx)
}

func (w *worker) deindexStale(ctx context.Context, job job) (int64, error) {
	query, args := staleDeleteQuery(job, true)
	command, err := w.pool.Exec(ctx, query, args...)
	return command.RowsAffected(), err
}

func (w *worker) deindexMissingScope(ctx context.Context, job job) (int64, error) {
	query, args := staleDeleteQuery(job, false)
	command, err := w.pool.Exec(ctx, query, args...)
	return command.RowsAffected(), err
}

func staleDeleteQuery(job job, onlyStale bool) (string, []any) {
	scope := ""
	args := []any{}
	if job.rootPath != "" {
		scope = " AND (image_path = $1 OR image_path LIKE $1 || '$%')"
		args = append(args, job.rootPath)
	}
	if onlyStale {
		args = append(args, job.id)
		return "DELETE FROM image WHERE last_index_job IS DISTINCT FROM $" + fmt.Sprint(len(args)) + scope, args
	}
	return "DELETE FROM image WHERE TRUE" + scope, args
}

func (w *worker) progress(ctx context.Context, job job, counts counters) bool {
	command, err := w.pool.Exec(ctx, `
UPDATE index_job
SET lease_expires_at = NOW() + $2::interval, discovered = $3, processed = $4,
    indexed = $5, updated = $6, skipped = $7, errors = $8
WHERE id = $1 AND status = 'running' AND worker_id = $9`,
		job.id, interval(leaseDuration), counts.discovered, counts.processed, counts.indexed,
		counts.updated, counts.skipped, counts.errors, w.workerID)
	return err == nil && command.RowsAffected() == 1
}

func (w *worker) cancelled(ctx context.Context, job job) bool {
	var status string
	if err := w.pool.QueryRow(ctx, "SELECT status FROM index_job WHERE id = $1", job.id).Scan(&status); err != nil {
		return true
	}
	return status == "cancelled"
}

func (w *worker) finish(ctx context.Context, job job, status, code string, counts counters) {
	_, err := w.pool.Exec(ctx, `
UPDATE index_job
SET status = $2, lease_expires_at = NULL, finished_at = NOW(), discovered = $3, processed = $4,
    indexed = $5, updated = $6, deindexed = $7, skipped = $8, errors = $9,
    error_code = NULLIF($10, '')
WHERE id = $1 AND worker_id = $11`, job.id, status, counts.discovered, counts.processed,
		counts.indexed, counts.updated, counts.deindexed, counts.skipped, counts.errors, code, w.workerID)
	if err != nil {
		w.log.Error("job completion update failed", "error", err)
		return
	}
	if job.requestedBy != nil && status == "succeeded" {
		_, _ = w.pool.Exec(ctx, `
INSERT INTO audit_event (actor_id, action, object_type, object_id, created_at)
VALUES ($1, 'index_tree', 'index_job', $2, NOW())`, job.requestedBy, job.id)
	}
	w.log.Info("index job completed", "status", status, "processed", counts.processed,
		"indexed", counts.indexed, "updated", counts.updated, "deindexed", counts.deindexed, "errors", counts.errors)
}

func (w *worker) jobRoot(rootPath string) (string, []string, error) {
	parts := []string{}
	if rootPath != "" {
		parts = strings.Split(rootPath, "$")
	}
	if !safeParts(parts) {
		return "", nil, errors.New("invalid root")
	}
	root := filepath.Join(append([]string{w.mediaRoot}, parts...)...)
	canonicalRoot, err := filepath.EvalSymlinks(w.mediaRoot)
	if err != nil {
		return "", nil, err
	}
	canonicalTarget, err := filepath.Abs(root)
	if err != nil {
		return "", nil, err
	}
	if canonicalTarget != canonicalRoot && !strings.HasPrefix(canonicalTarget, canonicalRoot+string(filepath.Separator)) {
		return "", nil, errors.New("outside media root")
	}
	return root, parts, nil
}

func safeParts(parts []string) bool {
	for _, part := range parts {
		if part == "" || part == "." || part == ".." || strings.ContainsAny(part, "$/\\\x00") {
			return false
		}
		for _, char := range part {
			if unicode.IsControl(char) {
				return false
			}
		}
	}
	return true
}

func supportedMedia(name string) bool {
	extension := strings.ToLower(filepath.Ext(name))
	switch extension {
	case ".avif", ".avi", ".bmp", ".gif", ".jpeg", ".jpg", ".m4v", ".mov", ".mp4", ".png", ".tif", ".tiff", ".webm", ".webp", ".wmv":
		return true
	default:
		return false
	}
}

func normalizeDatabaseURL(value string) string {
	return strings.Replace(value, "postgresql+psycopg://", "postgres://", 1)
}

func requiredEnv(name string) string {
	value := os.Getenv(name)
	if value == "" {
		fatal("required environment variable missing", errors.New(name))
	}
	return value
}

func envInt(name string, fallback int) int {
	value := os.Getenv(name)
	if value == "" {
		return fallback
	}
	var parsed int
	if _, err := fmt.Sscanf(value, "%d", &parsed); err != nil || parsed < 1 || parsed > 5000 {
		return fallback
	}
	return parsed
}

func workerIdentity() string {
	bytes := make([]byte, 6)
	if _, err := rand.Read(bytes); err != nil {
		return "worker"
	}
	return "worker-" + hex.EncodeToString(bytes)
}

func interval(value time.Duration) string {
	return fmt.Sprintf("%d seconds", int(value.Seconds()))
}

func fatal(message string, err error) {
	slog.Error(message, "error", err)
	os.Exit(1)
}
