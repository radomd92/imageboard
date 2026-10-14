package embedding

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"log"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Worker struct {
	Pool    *pgxpool.Pool
	Encoder Vectorizer
	Version string
}

type Job struct {
	ImageID  int32
	Revision int64
	Token    string
	Attempts int
}

func (w *Worker) Configure(ctx context.Context) error {
	version := w.Encoder.Version()
	tx, err := w.Pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `INSERT INTO embedding_setting (id, version, tag_weight)
VALUES (1, $1, $2) ON CONFLICT (id) DO NOTHING`, version, w.Encoder.TagWeight); err != nil {
		return err
	}
	var previous string
	if err := tx.QueryRow(ctx, `SELECT version FROM embedding_setting WHERE id = 1 FOR UPDATE`).Scan(&previous); err != nil {
		return err
	}
	if previous != version {
		if _, err := tx.Exec(ctx, `UPDATE image_embedding_job SET revision = revision + 1, status = 'pending',
available_at = NOW(), lease_token = NULL, lease_until = NULL, attempts = 0, last_error = NULL, updated_at = NOW()`); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `UPDATE embedding_setting SET version = $1, tag_weight = $2, updated_at = NOW() WHERE id = 1`, version, w.Encoder.TagWeight); err != nil {
			return err
		}
	}
	if _, err := tx.Exec(ctx, `INSERT INTO image_embedding_job (image_id)
SELECT i.id FROM image i WHERE EXISTS (SELECT 1 FROM tag_image ti WHERE ti.image = i.id)
OR EXISTS (SELECT 1 FROM message m WHERE m.image = i.id) ON CONFLICT (image_id) DO NOTHING`); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return err
	}
	w.Version = version
	return nil
}

func (w *Worker) Claim(ctx context.Context) (Job, error) {
	var token [16]byte
	if _, err := rand.Read(token[:]); err != nil {
		return Job{}, err
	}
	job := Job{Token: hex.EncodeToString(token[:])}
	err := w.Pool.QueryRow(ctx, `WITH candidate AS (
SELECT image_id FROM image_embedding_job WHERE status IN ('pending', 'failed', 'running') AND
((status IN ('pending', 'failed') AND available_at <= NOW()) OR (status = 'running' AND lease_until < NOW()))
ORDER BY priority DESC, available_at, image_id LIMIT 1 FOR UPDATE SKIP LOCKED)
UPDATE image_embedding_job j SET status = 'running', lease_token = $1::uuid,
lease_until = NOW() + INTERVAL '2 minutes', attempts = attempts + 1, updated_at = NOW()
FROM candidate c WHERE j.image_id = c.image_id RETURNING j.image_id, j.revision, j.attempts`, job.Token).Scan(&job.ImageID, &job.Revision, &job.Attempts)
	return job, err
}

func (w *Worker) source(ctx context.Context, job Job) (Source, error) {
	tx, err := w.Pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		return Source{}, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var current bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM image_embedding_job WHERE image_id = $1 AND revision = $2 AND lease_token = $3::uuid)`, job.ImageID, job.Revision, job.Token).Scan(&current); err != nil || !current {
		return Source{}, errors.New("lease no longer current")
	}
	source := Source{Tags: []string{}, Comments: []string{}}
	rows, err := tx.Query(ctx, `SELECT t.name FROM tag_image ti JOIN tag t ON t.id = ti.tag WHERE ti.image = $1 ORDER BY t.name`, job.ImageID)
	if err != nil {
		return Source{}, err
	}
	for rows.Next() {
		var text string
		if err := rows.Scan(&text); err != nil {
			rows.Close()
			return Source{}, err
		}
		source.Tags = append(source.Tags, text)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return Source{}, err
	}
	rows, err = tx.Query(ctx, `SELECT text FROM message WHERE image = $1 AND btrim(text) <> '' ORDER BY message_date, id`, job.ImageID)
	if err != nil {
		return Source{}, err
	}
	for rows.Next() {
		var text string
		if err := rows.Scan(&text); err != nil {
			rows.Close()
			return Source{}, err
		}
		source.Comments = append(source.Comments, text)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return Source{}, err
	}
	return source, tx.Commit(ctx)
}

// Publish only if both lease ownership and source revision still match.
func (w *Worker) Publish(ctx context.Context, job Job, hash string, vector map[string]float64) (bool, error) {
	tx, err := w.Pool.Begin(ctx)
	if err != nil {
		return false, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var id int32
	err = tx.QueryRow(ctx, `SELECT image_id FROM image_embedding_job WHERE image_id = $1 AND revision = $2
AND lease_token = $3::uuid AND lease_until > NOW() AND status = 'running' FOR UPDATE`, job.ImageID, job.Revision, job.Token).Scan(&id)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	var version string
	if err := tx.QueryRow(ctx, `SELECT version FROM embedding_setting WHERE id = 1`).Scan(&version); err != nil {
		return false, err
	}
	if version != w.Version {
		return false, nil
	}
	status := "ready"
	if len(vector) == 0 {
		status = "empty"
		if _, err := tx.Exec(ctx, `DELETE FROM image_embedding WHERE image_id = $1`, id); err != nil {
			return false, err
		}
	} else {
		if _, err := tx.Exec(ctx, `INSERT INTO image_embedding (image_id, version, source_hash, built_revision)
VALUES ($1, $2, $3, $4) ON CONFLICT (image_id) DO UPDATE SET
version = EXCLUDED.version, source_hash = EXCLUDED.source_hash,
built_revision = EXCLUDED.built_revision, updated_at = NOW()`, id, w.Version, hash, job.Revision); err != nil {
			return false, err
		}
		if _, err := tx.Exec(ctx, `DELETE FROM image_embedding_term WHERE image_id = $1`, id); err != nil {
			return false, err
		}
		rows := make([][]any, 0, len(vector))
		for term, weight := range vector {
			rows = append(rows, []any{id, term, weight})
		}
		if _, err := tx.CopyFrom(ctx, pgx.Identifier{"image_embedding_term"}, []string{"image_id", "term", "weight"}, pgx.CopyFromRows(rows)); err != nil {
			return false, err
		}
	}
	if _, err := tx.Exec(ctx, `UPDATE image_embedding_job SET status = $1, completed_revision = revision,
lease_token = NULL, lease_until = NULL, attempts = 0, last_error = NULL, updated_at = NOW() WHERE image_id = $2`, status, id); err != nil {
		return false, err
	}
	return true, tx.Commit(ctx)
}

func (w *Worker) Process(ctx context.Context, job Job) error {
	jobCtx, cancel := context.WithCancel(ctx)
	done := make(chan struct{})
	go func() {
		defer close(done)
		ticker := time.NewTicker(20 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-jobCtx.Done():
				return
			case <-ticker.C:
				result, err := w.Pool.Exec(jobCtx, `UPDATE image_embedding_job SET lease_until = NOW() + INTERVAL '2 minutes'
WHERE image_id = $1 AND revision = $2 AND lease_token = $3::uuid AND status = 'running'`, job.ImageID, job.Revision, job.Token)
				if err != nil || result.RowsAffected() == 0 {
					cancel()
					return
				}
			}
		}
	}()
	defer func() { cancel(); <-done }()
	source, err := w.source(jobCtx, job)
	if err != nil {
		return err
	}
	hash := SourceHash(source, w.Version)
	vector := w.Encoder.Vectorize(source)
	_, err = w.Publish(jobCtx, job, hash, vector)
	return err
}

func (w *Worker) Fail(ctx context.Context, job Job) error {
	delay := min(600, 5*(1<<min(job.Attempts, 7)))
	_, err := w.Pool.Exec(ctx, `UPDATE image_embedding_job SET status = 'failed', available_at = NOW() + $1 * INTERVAL '1 second',
lease_token = NULL, lease_until = NULL, last_error = 'embedding_failed', updated_at = NOW()
WHERE image_id = $2 AND revision = $3 AND lease_token = $4::uuid`, delay, job.ImageID, job.Revision, job.Token)
	return err
}

func (w *Worker) Run(ctx context.Context) {
	completed := 0
	for ctx.Err() == nil {
		job, err := w.Claim(ctx)
		if err != nil {
			if !errors.Is(err, pgx.ErrNoRows) && ctx.Err() == nil {
				log.Print("embedding queue unavailable")
			}
			select {
			case <-ctx.Done():
			case <-time.After(time.Second):
			}
			continue
		}
		if err := w.Process(ctx, job); err != nil {
			if ctx.Err() == nil {
				if err := w.Fail(ctx, job); err != nil {
					log.Print("embedding retry scheduling failed")
				}
				log.Printf("embedding job %d deferred", job.ImageID)
			}
		} else {
			completed++
			if completed%100 == 0 {
				log.Printf("embedding worker processed %d jobs", completed)
			}
		}
		// Yield between images to keep the background backfill light on CPU/DB.
		select {
		case <-ctx.Done():
		case <-time.After(20 * time.Millisecond):
		}
	}
}
