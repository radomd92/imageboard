package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
	"testing"

	"imageboard/api/internal/embedding"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestDiscoveryIntegration(t *testing.T) {
	url := os.Getenv("IMAGEBOARD_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("set IMAGEBOARD_TEST_DATABASE_URL to a migrated disposable PostgreSQL database")
	}
	ctx := context.Background()
	admin, err := pgxpool.New(ctx, url)
	if err != nil {
		t.Fatal("invalid test database configuration")
	}
	defer admin.Close()
	schema := "discovery_test_" + strings.ReplaceAll(uuid(), "-", "")
	quotedSchema := pgx.Identifier{schema}.Sanitize()
	if _, err := admin.Exec(ctx, "CREATE SCHEMA "+quotedSchema); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if _, err := admin.Exec(ctx, "DROP SCHEMA "+quotedSchema+" CASCADE"); err != nil {
			t.Error(err)
		}
	}()
	config, err := pgxpool.ParseConfig(url)
	if err != nil {
		t.Fatal(err)
	}
	config.ConnConfig.RuntimeParams["search_path"] = schema + ",public"
	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	for _, table := range []string{"user", "image", "message", "tag", "tag_image", "image_favorite", "image_hits", "embedding_setting", "image_embedding", "image_embedding_term", "image_embedding_job"} {
		name := pgx.Identifier{table}.Sanitize()
		if _, err := pool.Exec(ctx, "CREATE TABLE "+name+" (LIKE public."+name+" INCLUDING ALL)"); err != nil {
			t.Fatal("migrate disposable database to head before running discovery tests")
		}
	}
	// LIKE does not clone triggers/FKs. Attach real production trigger functions
	// with an isolated search_path and restore the relevant cascade constraints.
	if _, err := pool.Exec(ctx, `ALTER TABLE image_embedding ADD FOREIGN KEY (image_id) REFERENCES image(id) ON DELETE CASCADE;
ALTER TABLE image_embedding_job ADD FOREIGN KEY (image_id) REFERENCES image(id) ON DELETE CASCADE;
ALTER TABLE image_embedding_term ADD FOREIGN KEY (image_id) REFERENCES image_embedding(image_id) ON DELETE CASCADE;
ALTER TABLE message ADD FOREIGN KEY (image) REFERENCES image(id) ON DELETE CASCADE;
ALTER TABLE tag_image ADD FOREIGN KEY (image) REFERENCES image(id) ON DELETE CASCADE;
CREATE TRIGGER message_embedding_changed AFTER INSERT OR DELETE OR UPDATE OF text, image ON message FOR EACH ROW EXECUTE FUNCTION public.message_embedding_dirty();
CREATE TRIGGER tag_image_embedding_changed AFTER INSERT OR DELETE OR UPDATE ON tag_image FOR EACH ROW EXECUTE FUNCTION public.tag_image_embedding_dirty();
CREATE TRIGGER tag_name_embedding_changed AFTER UPDATE OF name ON tag FOR EACH ROW WHEN (OLD.name IS DISTINCT FROM NEW.name) EXECUTE FUNCTION public.tag_name_embedding_dirty();`); err != nil {
		t.Fatal(err)
	}
	app := &application{pool: pool, config: configForAccountTest(), authCache: map[string]cacheEntry{}, scryptSem: make(chan struct{}, 1)}
	password := "discovery-test-password"
	hash, err := app.hashPassword(password)
	if err != nil {
		t.Fatal(err)
	}
	var actor, otherActor int32
	for i, target := range []*int32{&actor, &otherActor} {
		if err := pool.QueryRow(ctx, `INSERT INTO "user" (name, password, registered, privileges, banned) VALUES ($1, $2, NOW(), 'user', FALSE) RETURNING id`, fmt.Sprintf("discovery-user-%d", i), hash).Scan(target); err != nil {
			t.Fatal(err)
		}
	}
	ids := []int32{}
	for i := 0; i < 14; i++ {
		var id int32
		if err := pool.QueryRow(ctx, `INSERT INTO image (image_path, name, hits) VALUES ($1, $2, $3) RETURNING id`, fmt.Sprintf("discovery$%d.jpg", i), fmt.Sprintf("Image %d", i), i).Scan(&id); err != nil {
			t.Fatal(err)
		}
		ids = append(ids, id)
		text := "red cat window"
		if i == 13 {
			text = "aircraft mountains"
		}
		if _, err := pool.Exec(ctx, `INSERT INTO message (from_user, image, text, message_date) VALUES ($1, $2, $3, NOW())`, actor, id, text); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := pool.Exec(ctx, `INSERT INTO image_favorite (user_id, image_id) VALUES ($1, $3), ($2, $3), ($1, $4)`, actor, otherActor, ids[0], ids[1]); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `INSERT INTO message (from_user, image, text, message_date) VALUES ($1, $2, 'cat', NOW()), ($1, $2, 'window', NOW())`, actor, ids[0]); err != nil {
		t.Fatal(err)
	}
	get := func(path string, want int) []byte {
		t.Helper()
		response := accountTestRequest(app, "discovery-user-0", password, "GET", path, nil)
		if response.Code != want {
			t.Fatalf("%s: got %d, want %d: %s", path, response.Code, want, response.Body.String())
		}
		return response.Body.Bytes()
	}
	var dashboard struct {
		Viewed    []imageSummary `json:"most_viewed"`
		Commented []imageSummary `json:"most_commented"`
		Favorited []imageSummary `json:"most_favorited"`
	}
	if err := json.Unmarshal(get("/api/dashboard", 200), &dashboard); err != nil {
		t.Fatal(err)
	}
	if len(dashboard.Viewed) != 8 || dashboard.Viewed[0].ID != ids[13] || dashboard.Commented[0].ID != ids[0] || dashboard.Commented[0].CommentCount != 3 || dashboard.Favorited[0].FavoriteCount != 2 || !dashboard.Favorited[0].Favorite {
		t.Fatalf("invalid rankings or multiplied counts: %#v", dashboard)
	}
	worker := embedding.Worker{Pool: pool, Encoder: embedding.Vectorizer{TagWeight: 2}}
	if err := worker.Configure(ctx); err != nil {
		t.Fatal(err)
	}
	processAll := func() {
		t.Helper()
		for {
			job, err := worker.Claim(ctx)
			if errors.Is(err, pgx.ErrNoRows) {
				break
			}
			if err != nil {
				t.Fatal(err)
			}
			if err := worker.Process(ctx, job); err != nil {
				t.Fatal(err)
			}
		}
	}
	processAll()
	var similar struct {
		Status string         `json:"status"`
		Items  []imageSummary `json:"items"`
	}
	if err := json.Unmarshal(get(fmt.Sprintf("/api/images/%d/similar", ids[0]), 200), &similar); err != nil {
		t.Fatal(err)
	}
	if similar.Status != "ready" || len(similar.Items) != 10 {
		t.Fatalf("missing top-ten results: %#v", similar)
	}
	for i, item := range similar.Items {
		if item.ID == ids[0] || item.ID == ids[13] || item.Score == nil || (i > 0 && *item.Score > *similar.Items[i-1].Score) {
			t.Fatal("invalid similarity order, self exclusion, or unrelated result")
		}
	}
	// A transaction containing several annotation writes increments once.
	if _, err := pool.Exec(ctx, `UPDATE image_embedding_job SET status = 'pending', priority = 0 WHERE image_id = $1`, ids[13]); err != nil {
		t.Fatal(err)
	}
	var before int64
	if err := pool.QueryRow(ctx, `SELECT revision FROM image_embedding_job WHERE image_id = $1`, ids[0]).Scan(&before); err != nil {
		t.Fatal(err)
	}
	tx, err := pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 3; i++ {
		if _, err := tx.Exec(ctx, `INSERT INTO message (from_user, image, text, message_date) VALUES ($1, $2, 'cat', NOW())`, actor, ids[0]); err != nil {
			t.Fatal(err)
		}
	}
	if err := tx.Commit(ctx); err != nil {
		t.Fatal(err)
	}
	var after int64
	if err := pool.QueryRow(ctx, `SELECT revision FROM image_embedding_job WHERE image_id = $1`, ids[0]).Scan(&after); err != nil || after != before+1 {
		t.Fatal("annotation queue was not coalesced transactionally")
	}
	job, err := worker.Claim(ctx)
	if err != nil || job.ImageID != ids[0] {
		t.Fatal("changed image did not take priority over backfill")
	}
	if _, err := pool.Exec(ctx, `UPDATE message SET text = 'blue ocean' WHERE image = $1`, ids[0]); err != nil {
		t.Fatal(err)
	}
	if published, err := worker.Publish(ctx, job, "obsolete", map[string]float64{"w:cat": 1}); err != nil || published {
		t.Fatal("obsolete source revision was published")
	}
	processAll()
	var tagID int32
	if err := pool.QueryRow(ctx, `INSERT INTO tag (name) VALUES ('cat') RETURNING id`).Scan(&tagID); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `INSERT INTO tag_image (tag, image) VALUES ($1, $2)`, tagID, ids[1]); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(get(fmt.Sprintf("/api/images/%d/similar", ids[1]), 200), &similar); err != nil || similar.Status != "indexing" || len(similar.Items) != 0 {
		t.Fatal("dirty tag vectors remained visible")
	}
	processAll()
	if err := pool.QueryRow(ctx, `SELECT revision FROM image_embedding_job WHERE image_id = $1`, ids[1]).Scan(&before); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `UPDATE tag SET name = 'fox' WHERE id = $1`, tagID); err != nil {
		t.Fatal(err)
	}
	if err := pool.QueryRow(ctx, `SELECT revision FROM image_embedding_job WHERE image_id = $1`, ids[1]).Scan(&after); err != nil || after != before+1 {
		t.Fatal("tag rename did not invalidate attached images")
	}
	processAll()
	if err := pool.QueryRow(ctx, `SELECT revision FROM image_embedding_job WHERE image_id = $1`, ids[2]).Scan(&before); err != nil {
		t.Fatal(err)
	}
	tx, err = pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := tx.Exec(ctx, `INSERT INTO message (from_user, image, text, message_date) VALUES ($1, $2, 'rollback', NOW())`, actor, ids[2]); err != nil {
		t.Fatal(err)
	}
	if err := tx.Rollback(ctx); err != nil {
		t.Fatal(err)
	}
	if err := pool.QueryRow(ctx, `SELECT revision FROM image_embedding_job WHERE image_id = $1`, ids[2]).Scan(&after); err != nil || after != before {
		t.Fatal("rolled-back annotation left queued work")
	}
	if _, err := pool.Exec(ctx, `INSERT INTO message (from_user, image, text, message_date) VALUES ($1, $2, 'lease recovery', NOW())`, actor, ids[2]); err != nil {
		t.Fatal(err)
	}
	oldJob, err := worker.Claim(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `UPDATE image_embedding_job SET lease_until = NOW() - INTERVAL '1 second' WHERE image_id = $1`, oldJob.ImageID); err != nil {
		t.Fatal(err)
	}
	recovered, err := worker.Claim(ctx)
	if err != nil || recovered.ImageID != oldJob.ImageID || recovered.Token == oldJob.Token {
		t.Fatal("expired lease was not recovered")
	}
	if published, err := worker.Publish(ctx, oldJob, "obsolete", map[string]float64{"w:cat": 1}); err != nil || published {
		t.Fatal("old lease owner published a result")
	}
	if err := worker.Fail(ctx, recovered); err != nil {
		t.Fatal(err)
	}
	if _, err := worker.Claim(ctx); !errors.Is(err, pgx.ErrNoRows) {
		t.Fatal("failed job was retried without backoff")
	}
	if _, err := pool.Exec(ctx, `UPDATE image_embedding_job SET available_at = NOW() WHERE image_id = $1`, recovered.ImageID); err != nil {
		t.Fatal(err)
	}
	processAll()
	if _, err := pool.Exec(ctx, `DELETE FROM message WHERE image = $1`, ids[3]); err != nil {
		t.Fatal(err)
	}
	processAll()
	if err := json.Unmarshal(get(fmt.Sprintf("/api/images/%d/similar", ids[3]), 200), &similar); err != nil || similar.Status != "no_context" {
		t.Fatal("empty context did not clear vector")
	}
	worker.Encoder.TagWeight = 3
	if err := worker.Configure(ctx); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(get(fmt.Sprintf("/api/images/%d/similar", ids[1]), 200), &similar); err != nil || similar.Status != "indexing" {
		t.Fatal("algorithm changes did not schedule a rebuild")
	}
	processAll()
	if _, err := pool.Exec(ctx, `DELETE FROM image WHERE id = $1`, ids[0]); err != nil {
		t.Fatal(err)
	}
	var remaining int64
	if err := pool.QueryRow(ctx, `SELECT (SELECT count(*) FROM image_embedding_job WHERE image_id = $1) + (SELECT count(*) FROM image_embedding_term WHERE image_id = $1)`, ids[0]).Scan(&remaining); err != nil || remaining != 0 {
		t.Fatal("deindexing did not cascade vector/job cleanup")
	}
	get(fmt.Sprintf("/api/images/%d/similar", ids[0]), 404)
}
