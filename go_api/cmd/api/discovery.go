package main

import (
	"context"
	"errors"
	"net/http"
	"time"

	"github.com/jackc/pgx/v5"
)

// Discovery cards deliberately omit full comment threads.
type imageSummary struct {
	ID            int32     `json:"id"`
	Name          string    `json:"name"`
	Kind          string    `json:"kind"`
	ThumbURL      string    `json:"thumbnail_url"`
	FileSize      *int64    `json:"file_size"`
	CreatedAt     time.Time `json:"created_at"`
	Hits          int32     `json:"hits"`
	CommentCount  int64     `json:"comment_count"`
	FavoriteCount int64     `json:"favorite_count"`
	Favorite      bool      `json:"favorite"`
	Tags          []string  `json:"tags"`
	Score         *float64  `json:"similarity,omitempty"`
}

func (a *application) imageSummaries(ctx context.Context, ids []int32, userID int32) ([]imageSummary, error) {
	items := []imageSummary{}
	if len(ids) == 0 {
		return items, nil
	}
	rows, err := a.pool.Query(ctx, `SELECT i.id, i.name, i.image_path, i.file_size, i.created_date, i.hits,
(SELECT count(*) FROM message m WHERE m.image = i.id),
(SELECT count(*) FROM image_favorite f WHERE f.image_id = i.id),
EXISTS (SELECT 1 FROM image_favorite f WHERE f.image_id = i.id AND f.user_id = $2),
ARRAY(SELECT t.name FROM tag_image ti JOIN tag t ON t.id = ti.tag WHERE ti.image = i.id ORDER BY t.name)
FROM image i WHERE i.id = ANY($1) ORDER BY array_position($1::integer[], i.id)`, ids, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var item imageSummary
		var path string
		if err := rows.Scan(&item.ID, &item.Name, &path, &item.FileSize, &item.CreatedAt, &item.Hits, &item.CommentCount, &item.FavoriteCount, &item.Favorite, &item.Tags); err != nil {
			return nil, err
		}
		item.Kind = mediaKind(path)
		item.ThumbURL = "/thumbnail/" + encodedPath(path) + "/small"
		items = append(items, item)
	}
	return items, rows.Err()
}

func (a *application) rankedImages(ctx context.Context, currentUser user) (map[string][]imageSummary, error) {
	queries := []struct{ name, sql string }{
		{"most_viewed", `SELECT id FROM image WHERE hits > 0 ORDER BY hits DESC, id DESC LIMIT 8`},
		{"most_commented", `SELECT image FROM message GROUP BY image ORDER BY count(*) DESC, image DESC LIMIT 8`},
		{"most_favorited", `SELECT image_id FROM image_favorite GROUP BY image_id ORDER BY count(*) DESC, image_id DESC LIMIT 8`},
	}
	result := map[string][]imageSummary{}
	for _, query := range queries {
		rows, err := a.pool.Query(ctx, query.sql)
		if err != nil {
			return nil, err
		}
		ids := []int32{}
		for rows.Next() {
			var id int32
			if err := rows.Scan(&id); err != nil {
				rows.Close()
				return nil, err
			}
			ids = append(ids, id)
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return nil, err
		}
		items, err := a.imageSummaries(ctx, ids, currentUser.ID)
		if err != nil {
			return nil, err
		}
		result[query.name] = items
	}
	return result, nil
}

func (a *application) similarImages(w http.ResponseWriter, r *http.Request, currentUser user) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	var exists bool
	if err := a.pool.QueryRow(r.Context(), `SELECT EXISTS (SELECT 1 FROM image WHERE id = $1)`, id).Scan(&exists); err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	if !exists {
		writeError(w, 404, "Image not found")
		return
	}
	var status string
	var valid bool
	err := a.pool.QueryRow(r.Context(), `SELECT j.status,
COALESCE(j.status = 'ready' AND e.built_revision = j.revision AND e.version = s.version, FALSE)
FROM image_embedding_job j LEFT JOIN image_embedding e ON e.image_id = j.image_id
LEFT JOIN embedding_setting s ON s.id = 1 WHERE j.image_id = $1`, id).Scan(&status, &valid)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		writeError(w, 500, "Database unavailable")
		return
	}
	state := "indexing"
	if errors.Is(err, pgx.ErrNoRows) || status == "empty" {
		state = "no_context"
	} else if status == "failed" {
		state = "retrying"
	}
	if !valid {
		writeJSON(w, 200, map[string]any{"status": state, "items": []imageSummary{}})
		return
	}
	// The term index retrieves only overlapping vectors. A normalized sparse
	// dot product is cosine similarity, without scanning unrelated images.
	rows, err := a.pool.Query(r.Context(), `WITH scores AS MATERIALIZED (
SELECT candidate.image_id, sum(seed.weight * candidate.weight) AS score
FROM image_embedding_term seed JOIN image_embedding_term candidate ON candidate.term = seed.term
WHERE seed.image_id = $1 AND candidate.image_id <> $1 GROUP BY candidate.image_id)
SELECT scores.image_id, scores.score FROM scores
JOIN image_embedding e ON e.image_id = scores.image_id
JOIN image_embedding_job j ON j.image_id = e.image_id
JOIN embedding_setting s ON s.id = 1
WHERE j.status = 'ready' AND e.built_revision = j.revision AND e.version = s.version
AND EXISTS (SELECT 1 FROM image_embedding seed_e JOIN image_embedding_job seed_j ON seed_j.image_id = seed_e.image_id
WHERE seed_e.image_id = $1 AND seed_j.status = 'ready' AND seed_e.built_revision = seed_j.revision AND seed_e.version = s.version)
ORDER BY scores.score DESC, scores.image_id DESC LIMIT 10`, id)
	if err != nil {
		writeError(w, 500, "Similarity search unavailable")
		return
	}
	ids := []int32{}
	scores := map[int32]float64{}
	for rows.Next() {
		var candidate int32
		var score float64
		if err := rows.Scan(&candidate, &score); err != nil {
			rows.Close()
			writeError(w, 500, "Similarity search unavailable")
			return
		}
		ids = append(ids, candidate)
		scores[candidate] = score
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		writeError(w, 500, "Similarity search unavailable")
		return
	}
	items, err := a.imageSummaries(r.Context(), ids, currentUser.ID)
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	for i := range items {
		score := scores[items[i].ID]
		items[i].Score = &score
	}
	writeJSON(w, 200, map[string]any{"status": "ready", "items": items})
}
