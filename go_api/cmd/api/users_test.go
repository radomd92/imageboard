package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestAccountPasswordHashes(t *testing.T) {
	app := application{scryptSem: make(chan struct{}, 1)}
	password := "correct horse battery staple"
	first, err := app.hashPassword(password)
	if err != nil {
		t.Fatal(err)
	}
	second, err := app.hashPassword(password)
	if err != nil {
		t.Fatal(err)
	}
	if first == second || !strings.HasPrefix(first, "scrypt:32768:8:1$") {
		t.Fatal("hashes must have independent random salts and the compatible scrypt format")
	}
	if !app.verifyPassword(first, password) || app.verifyPassword(first, "wrong password") {
		t.Fatal("password hash verification failed")
	}
	// Empty or truncated digest must never authenticate.
	for _, malformed := range []string{"scrypt:32768:8:1$salt$", "scrypt:32768:8:1$salt$00", "scrypt:3:8:1$salt$" + strings.Repeat("00", 64)} {
		if app.verifyPassword(malformed, password) {
			t.Fatal("malformed hash authenticated")
		}
	}
}

func TestAccountValidation(t *testing.T) {
	for _, name := range []string{"abc", "élève", strings.Repeat("界", 100)} {
		if !validUsername(name) {
			t.Fatalf("valid username rejected: %q", name)
		}
	}
	for _, name := range []string{"ab", " abc", "abc ", "abc:def", "abc\n", strings.Repeat("界", 101), "abc\xff"} {
		if validUsername(name) {
			t.Fatalf("invalid username accepted: %q", name)
		}
	}
	for _, password := range []string{strings.Repeat("a", 14), strings.Repeat("界", 256)} {
		if !validNewPassword(password) {
			t.Fatal("valid password rejected")
		}
	}
	for _, password := range []string{strings.Repeat("a", 13), strings.Repeat("a", 257), strings.Repeat("a", 14) + "\x00"} {
		if validNewPassword(password) {
			t.Fatal("invalid password accepted")
		}
	}
}

func TestAccountWriteProtection(t *testing.T) {
	app := application{}
	tests := []struct {
		name, contentType, custom, origin, site string
		status                                  int
	}{
		{"same origin", "application/json", "account", "https://board.test:8443", "same-origin", 204},
		{"CLI", "application/json", "account", "", "", 204},
		{"missing custom header", "application/json", "", "", "", 403},
		{"form post", "application/x-www-form-urlencoded", "account", "", "", 403},
		{"foreign origin", "application/json", "account", "https://evil.test", "", 403},
		{"wrong port", "application/json", "account", "https://board.test", "", 403},
		{"null origin", "application/json", "account", "null", "", 403},
		{"same site is not same origin", "application/json", "account", "", "same-site", 403},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			r := httptest.NewRequest("PUT", "https://board.test:8443/api/me/password", nil)
			r.Header.Set("Content-Type", test.contentType)
			r.Header.Set("X-Imageboard-Request", test.custom)
			r.Header.Set("Origin", test.origin)
			r.Header.Set("Sec-Fetch-Site", test.site)
			w := httptest.NewRecorder()
			app.accountWrite(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(204) })(w, r)
			if w.Code != test.status {
				t.Fatalf("got %d, want %d", w.Code, test.status)
			}
		})
	}
	for _, body := range []string{`{"password":"one"} {"password":"two"}`, `{"unexpected":true}`, strings.Repeat(" ", 8193)} {
		r := httptest.NewRequest("PUT", "/api/me/password", strings.NewReader(body))
		w := httptest.NewRecorder()
		var target struct {
			Password string `json:"password"`
		}
		if decodeAccountJSON(w, r, &target) {
			t.Fatal("invalid account JSON accepted")
		}
	}
}

func TestAccountManagementIntegration(t *testing.T) {
	// This explicit URL must point to a disposable database migrated to head.
	databaseURL := os.Getenv("IMAGEBOARD_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("set IMAGEBOARD_TEST_DATABASE_URL to a migrated disposable PostgreSQL database")
	}
	ctx := context.Background()
	adminPool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatal("cannot configure test database")
	}
	defer adminPool.Close()
	schema := "account_test_" + strings.ReplaceAll(uuid(), "-", "")
	quotedSchema := pgx.Identifier{schema}.Sanitize()
	if _, err := adminPool.Exec(ctx, "CREATE SCHEMA "+quotedSchema); err != nil {
		t.Fatal("cannot create isolated test schema")
	}
	defer func() {
		if _, err := adminPool.Exec(ctx, "DROP SCHEMA "+quotedSchema+" CASCADE"); err != nil {
			t.Error("cannot remove isolated test schema")
		}
	}()
	config, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		t.Fatal("cannot configure test pool")
	}
	config.ConnConfig.RuntimeParams["search_path"] = schema
	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		t.Fatal("cannot create test pool")
	}
	defer pool.Close()
	for _, table := range []string{"user", "image", "message", "audit_event", "tag", "tag_image", "image_favorite", "image_hits"} {
		quotedTable := pgx.Identifier{table}.Sanitize()
		if _, err := pool.Exec(ctx, "CREATE TABLE "+quotedTable+" (LIKE public."+quotedTable+" INCLUDING ALL)"); err != nil {
			t.Fatalf("test database must be migrated: cannot clone %s", table)
		}
	}
	newApp := func() *application {
		return &application{pool: pool, config: configForAccountTest(), authCache: map[string]cacheEntry{}, scryptSem: make(chan struct{}, 2)}
	}
	app, replica := newApp(), newApp()
	password := "initial-test-password"
	hash, err := app.hashPassword(password)
	if err != nil {
		t.Fatal(err)
	}
	insertUser := func(name, role string) int32 {
		t.Helper()
		var id int32
		if err := pool.QueryRow(ctx, `INSERT INTO "user" (name, password, privileges, registered, banned) VALUES ($1, $2, $3, NOW(), FALSE) RETURNING id`, name, hash, role).Scan(&id); err != nil {
			t.Fatal(err)
		}
		return id
	}
	rootID, memberID := insertUser("root-admin", "admin"), insertUser("member", "user")
	request := func(target *application, name, pass, method, path string, body any, want int) []byte {
		t.Helper()
		w := accountTestRequest(target, name, pass, method, path, body)
		if w.Code != want {
			t.Fatalf("%s %s: got %d, want %d: %s", method, path, w.Code, want, w.Body.String())
		}
		return w.Body.Bytes()
	}
	for _, endpoint := range []struct{ method, path string }{
		{"GET", "/api/admin/users"}, {"POST", "/api/admin/users"},
		{"PATCH", fmt.Sprintf("/api/admin/users/%d", rootID)},
		{"PUT", fmt.Sprintf("/api/admin/users/%d/password", rootID)},
	} {
		request(app, "member", password, endpoint.method, endpoint.path, map[string]any{}, 403)
	}
	request(app, "", "", "GET", "/api/users/1", nil, 401)
	request(app, "root-admin", password, "PATCH", fmt.Sprintf("/api/admin/users/%d", rootID), map[string]bool{"admin": false}, 409)
	request(app, "root-admin", password, "PATCH", fmt.Sprintf("/api/admin/users/%d", rootID), map[string]bool{"disabled": true}, 409)
	body := request(app, "root-admin", password, "POST", "/api/admin/users", map[string]any{"name": "new-member", "password": password, "admin": false}, 201)
	if bytes.Contains(body, []byte("password")) || bytes.Contains(body, []byte("scrypt:")) {
		t.Fatal("account response exposed password information")
	}
	request(app, "root-admin", password, "POST", "/api/admin/users", map[string]any{"name": "new-member", "password": password}, 409)
	request(app, "root-admin", password, "PATCH", "/api/admin/users/2147483647", map[string]bool{"admin": true}, 404)
	request(app, "member", password, "PUT", "/api/me/password", map[string]any{"password": "changed-test-password", "current_password": password, "id": rootID}, 422)
	request(app, "member", password, "PUT", "/api/me/password", map[string]any{"password": "changed-test-password", "current_password": "wrong"}, 422)
	// Warm independent caches; both must reject old credentials after mutation.
	request(replica, "member", password, "GET", "/api/me", nil, 200)
	request(app, "member", password, "PUT", "/api/me/password", map[string]any{"password": "changed-test-password", "current_password": password}, 204)
	for _, target := range []*application{app, replica} {
		request(target, "member", password, "GET", "/api/me", nil, 401)
		request(target, "member", "changed-test-password", "GET", "/api/me", nil, 200)
	}
	memberPath := fmt.Sprintf("/api/admin/users/%d", memberID)
	request(app, "root-admin", password, "PATCH", memberPath, map[string]bool{"admin": true}, 200)
	request(replica, "member", "changed-test-password", "GET", "/api/admin/users", nil, 200)
	request(app, "root-admin", password, "PATCH", memberPath, map[string]bool{"admin": false}, 200)
	request(replica, "member", "changed-test-password", "GET", "/api/admin/users", nil, 403)
	request(app, "root-admin", password, "PUT", memberPath+"/password", map[string]string{"password": "reset-test-password"}, 204)
	request(replica, "member", "changed-test-password", "GET", "/api/me", nil, 401)
	request(replica, "member", "reset-test-password", "GET", "/api/me", nil, 200)
	request(app, "root-admin", password, "PATCH", memberPath, map[string]bool{"disabled": true}, 200)
	request(replica, "member", "reset-test-password", "GET", "/api/me", nil, 401)
	request(app, "root-admin", password, "PATCH", memberPath, map[string]bool{"disabled": false}, 200)
	request(replica, "member", "reset-test-password", "GET", "/api/me", nil, 200)
	// Direct CLI-style password updates must also invalidate cached proofs.
	if _, err := pool.Exec(ctx, `UPDATE "user" SET password = $1 WHERE id = $2`, hash, memberID); err != nil {
		t.Fatal(err)
	}
	request(replica, "member", "reset-test-password", "GET", "/api/me", nil, 401)
	request(replica, "member", password, "GET", "/api/me", nil, 200)
	if _, err := pool.Exec(ctx, `UPDATE "user" SET banned = TRUE, password = '!disabled-reset-required!' WHERE id = $1`, memberID); err != nil {
		t.Fatal(err)
	}
	request(app, "root-admin", password, "PATCH", memberPath, map[string]bool{"disabled": false}, 409)
	request(app, "root-admin", password, "PUT", memberPath+"/password", map[string]string{"password": password}, 204)
	request(app, "root-admin", password, "PATCH", memberPath, map[string]bool{"disabled": false}, 200)
	// Identical timestamps exercise the ID tie-breaker across multiple images.
	var imageIDs [2]int32
	for i := range imageIDs {
		if err := pool.QueryRow(ctx, `INSERT INTO image (image_path, name) VALUES ($1, $2) RETURNING id`, fmt.Sprintf("test$%d.jpg", i), fmt.Sprintf("Image %d", i)).Scan(&imageIDs[i]); err != nil {
			t.Fatal(err)
		}
	}
	var commentIDs []int32
	for i := 0; i < 3; i++ {
		var id int32
		if err := pool.QueryRow(ctx, `INSERT INTO message (from_user, image, text, message_date) VALUES ($1, $2, $3, '2026-01-01T00:00:00Z') RETURNING id`, memberID, imageIDs[i%2], fmt.Sprintf("Comment %d", i)).Scan(&id); err != nil {
			t.Fatal(err)
		}
		commentIDs = append(commentIDs, id)
	}
	cursor := ""
	for i := 2; i >= 0; i-- {
		body := request(app, "root-admin", password, "GET", fmt.Sprintf("/api/users/%d/comments?limit=1&cursor=%s", memberID, cursor), nil, 200)
		var history struct {
			Items      []historyComment `json:"items"`
			NextCursor string           `json:"next_cursor"`
		}
		if err := json.Unmarshal(body, &history); err != nil || len(history.Items) != 1 || history.Items[0].ID != commentIDs[i] || history.Items[0].AuthorID == nil || *history.Items[0].AuthorID != memberID {
			t.Fatalf("incorrect paginated history: %s", body)
		}
		cursor = history.NextCursor
		if (cursor == "") != (i == 0) {
			t.Fatal("incorrect history continuation")
		}
	}
	request(app, "root-admin", password, "GET", fmt.Sprintf("/api/users/%d/comments?cursor=bad", memberID), nil, 422)
	body = request(app, "root-admin", password, "GET", fmt.Sprintf("/api/images/%d", imageIDs[0]), nil, 200)
	var media image
	if err := json.Unmarshal(body, &media); err != nil || len(media.Comments) != 2 || media.Comments[0].AuthorID == nil {
		t.Fatalf("missing comment author links: %s", body)
	}
	// Concurrent self-demotions may leave exactly one active admin, never zero.
	otherAdminID := insertUser("other-admin", "admin")
	statuses := make(chan int, 2)
	var group sync.WaitGroup
	for _, actor := range []struct {
		name string
		id   int32
	}{{"root-admin", rootID}, {"other-admin", otherAdminID}} {
		group.Add(1)
		go func() {
			defer group.Done()
			statuses <- accountTestRequest(app, actor.name, password, "PATCH", fmt.Sprintf("/api/admin/users/%d", actor.id), map[string]bool{"admin": false}).Code
		}()
	}
	group.Wait()
	first, second := <-statuses, <-statuses
	counts := map[int]int{}
	counts[first]++
	counts[second]++
	if counts[200] != 1 || counts[409] != 1 {
		t.Fatalf("concurrent last-admin protection failed: %d, %d", first, second)
	}
	var auditCount int64
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM audit_event WHERE object_type = 'user'`).Scan(&auditCount); err != nil || auditCount < 10 {
		t.Fatal("successful account changes were not audited")
	}
}

func configForAccountTest() config {
	return config{authTTL: time.Hour, authCacheKey: []byte("account-test-cache-key"), mediaURL: "/media"}
}

func accountTestRequest(app *application, name, password, method, path string, body any) *httptest.ResponseRecorder {
	encoded, _ := json.Marshal(body)
	r := httptest.NewRequest(method, path, bytes.NewReader(encoded))
	if name != "" {
		r.SetBasicAuth(name, password)
	}
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("X-Imageboard-Request", "account")
	w := httptest.NewRecorder()
	app.routes().ServeHTTP(w, r)
	return w
}

func TestCommentCursorValidation(t *testing.T) {
	value := base64.RawURLEncoding.EncodeToString([]byte("2026-01-01T00:00:00Z,42"))
	date, id, err := parseCommentCursor(value)
	if err != nil || id != 42 || date.Year() != 2026 {
		t.Fatal("valid cursor rejected")
	}
	for _, cursor := range []string{"bad", strings.Repeat("a", 101), base64.RawURLEncoding.EncodeToString([]byte("2026-01-01T00:00:00Z,0"))} {
		if _, _, err := parseCommentCursor(cursor); err == nil {
			t.Fatal("invalid cursor accepted")
		}
	}
}
