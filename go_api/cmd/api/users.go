package main

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"mime"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"golang.org/x/crypto/scrypt"
)

type accountSummary struct {
	ID         int32     `json:"id"`
	Name       string    `json:"name"`
	Admin      bool      `json:"admin"`
	Disabled   bool      `json:"disabled"`
	Registered time.Time `json:"registered"`
}

// Browser Basic credentials are ambient: writes require a same-origin custom
// header and JSON. No cross-origin preflight is allowed by this application.
func (a *application) accountWrite(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		mediaType, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
		if err != nil || mediaType != "application/json" || r.Header.Get("X-Imageboard-Request") != "account" {
			writeError(w, http.StatusForbidden, "Same-origin JSON request required")
			return
		}
		if site := r.Header.Get("Sec-Fetch-Site"); site != "" && site != "same-origin" && site != "none" {
			writeError(w, http.StatusForbidden, "Cross-origin request rejected")
			return
		}
		if origin := r.Header.Get("Origin"); origin != "" {
			parsed, parseErr := url.Parse(origin)
			scheme := r.Header.Get("X-Forwarded-Proto")
			if scheme == "" {
				scheme = "http"
				if r.TLS != nil {
					scheme = "https"
				}
			}
			if parseErr != nil || parsed.Scheme != scheme || !strings.EqualFold(parsed.Host, r.Host) || parsed.User != nil || parsed.Path != "" || parsed.RawQuery != "" || parsed.Fragment != "" {
				writeError(w, http.StatusForbidden, "Cross-origin request rejected")
				return
			}
		}
		next(w, r)
	}
}

func validUsername(name string) bool {
	length := utf8.RuneCountInString(name)
	return utf8.ValidString(name) && length >= 3 && length <= 100 && name == strings.TrimSpace(name) && !strings.Contains(name, ":") && !containsControl(name)
}

func validNewPassword(password string) bool {
	return utf8.ValidString(password) && utf8.RuneCountInString(password) >= 14 && utf8.RuneCountInString(password) <= 256 && len(password) <= 1024 && !containsControl(password)
}

func (a *application) hashPassword(password string) (string, error) {
	var saltBytes [16]byte
	if _, err := rand.Read(saltBytes[:]); err != nil {
		return "", err
	}
	salt := hex.EncodeToString(saltBytes[:])
	a.scryptSem <- struct{}{}
	digest, err := scrypt.Key([]byte(password), []byte(salt), 32768, 8, 1, 64)
	<-a.scryptSem
	if err != nil {
		return "", err
	}
	return "scrypt:32768:8:1$" + salt + "$" + hex.EncodeToString(digest), nil
}

func decodeAccountJSON(w http.ResponseWriter, r *http.Request, target any) bool {
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8192))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		writeError(w, http.StatusUnprocessableEntity, "Invalid account request")
		return false
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		writeError(w, http.StatusUnprocessableEntity, "Supply one JSON object")
		return false
	}
	return true
}

func userPathID(w http.ResponseWriter, r *http.Request) (int32, bool) {
	id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 32)
	if err != nil || id < 1 {
		writeError(w, http.StatusNotFound, "User not found")
		return 0, false
	}
	return int32(id), true
}

// Serialize account writes to preserve the last active administrator. Recheck
// the actor after acquiring the lock so a waiting demoted/reset actor fails.
func (a *application) beginAccountChange(w http.ResponseWriter, r *http.Request, actor user, admin bool) (pgx.Tx, bool) {
	tx, err := a.pool.Begin(r.Context())
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return nil, false
	}
	if _, err = tx.Exec(r.Context(), "SELECT pg_advisory_xact_lock(734921, 1)"); err != nil {
		_ = tx.Rollback(r.Context())
		writeError(w, 500, "Database unavailable")
		return nil, false
	}
	var hash, role string
	var disabled bool
	err = tx.QueryRow(r.Context(), `SELECT password, privileges, banned FROM "user" WHERE id = $1`, actor.ID).Scan(&hash, &role, &disabled)
	_, password, _ := r.BasicAuth()
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && (disabled || !a.verifyPassword(hash, password))) {
		_ = tx.Rollback(r.Context())
		w.Header().Set("WWW-Authenticate", "Basic")
		writeError(w, 401, "Authentication required")
		return nil, false
	}
	if err != nil {
		_ = tx.Rollback(r.Context())
		writeError(w, 500, "Database unavailable")
		return nil, false
	}
	if admin && role != "admin" {
		_ = tx.Rollback(r.Context())
		writeError(w, 403, "Administrator access required")
		return nil, false
	}
	return tx, true
}

func auditAccount(ctx context.Context, tx pgx.Tx, actorID, targetID int32, action string) error {
	_, err := tx.Exec(ctx, `INSERT INTO audit_event (actor_id, action, object_type, object_id, created_at) VALUES ($1, $2, 'user', $3, NOW())`, actorID, action, strconv.Itoa(int(targetID)))
	return err
}

func (a *application) listUsers(w http.ResponseWriter, r *http.Request, _ user) {
	q := r.URL.Query().Get("q")
	if !utf8.ValidString(q) || utf8.RuneCountInString(q) > 100 {
		writeError(w, 422, "Invalid username query")
		return
	}
	page, limit := positiveInt(r.URL.Query().Get("page"), 1), positiveInt(r.URL.Query().Get("limit"), 30)
	if limit > 100 {
		limit = 100
	}
	if page > 1000000 {
		writeError(w, 422, "Page out of range")
		return
	}
	var total int64
	if err := a.pool.QueryRow(r.Context(), `SELECT count(*) FROM "user" WHERE strpos(lower(name), lower($1)) > 0 OR $1 = ''`, q).Scan(&total); err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	rows, err := a.pool.Query(r.Context(), `SELECT id, name, privileges = 'admin', banned, registered FROM "user" WHERE strpos(lower(name), lower($1)) > 0 OR $1 = '' ORDER BY name, id LIMIT $2 OFFSET $3`, q, limit, (page-1)*limit)
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	defer rows.Close()
	items := []accountSummary{}
	for rows.Next() {
		var item accountSummary
		if err := rows.Scan(&item.ID, &item.Name, &item.Admin, &item.Disabled, &item.Registered); err != nil {
			writeError(w, 500, "Database unavailable")
			return
		}
		items = append(items, item)
	}
	if rows.Err() != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	writeJSON(w, 200, map[string]any{"items": items, "total": total, "page": page, "limit": limit})
}

func (a *application) createUser(w http.ResponseWriter, r *http.Request, actor user) {
	var body struct {
		Name     string `json:"name"`
		Password string `json:"password"`
		Admin    bool   `json:"admin"`
	}
	if !decodeAccountJSON(w, r, &body) {
		return
	}
	if !validUsername(body.Name) || !validNewPassword(body.Password) {
		writeError(w, 422, "Username must be 3–100 characters without colon, control characters, or surrounding whitespace; password must be 14–256 characters without control characters")
		return
	}
	hash, err := a.hashPassword(body.Password)
	if err != nil {
		writeError(w, 500, "Password hashing failed")
		return
	}
	tx, ok := a.beginAccountChange(w, r, actor, true)
	if !ok {
		return
	}
	defer func() { _ = tx.Rollback(r.Context()) }()
	role := "user"
	if body.Admin {
		role = "admin"
	}
	var result accountSummary
	err = tx.QueryRow(r.Context(), `INSERT INTO "user" (name, password, registered, privileges, banned) VALUES ($1, $2, NOW(), $3, FALSE) RETURNING id, name, privileges = 'admin', banned, registered`, body.Name, hash, role).Scan(&result.ID, &result.Name, &result.Admin, &result.Disabled, &result.Registered)
	var pgError *pgconn.PgError
	if errors.As(err, &pgError) && pgError.Code == "23505" {
		writeError(w, 409, "Username already exists")
		return
	}
	if err != nil || auditAccount(r.Context(), tx, actor.ID, result.ID, "create_user") != nil || tx.Commit(r.Context()) != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	writeJSON(w, http.StatusCreated, result)
}

func (a *application) updateUser(w http.ResponseWriter, r *http.Request, actor user) {
	id, ok := userPathID(w, r)
	if !ok {
		return
	}
	var body struct {
		Admin    *bool `json:"admin"`
		Disabled *bool `json:"disabled"`
	}
	if !decodeAccountJSON(w, r, &body) {
		return
	}
	if body.Admin == nil && body.Disabled == nil {
		writeError(w, 422, "Supply admin or disabled status")
		return
	}
	tx, ok := a.beginAccountChange(w, r, actor, true)
	if !ok {
		return
	}
	defer func() { _ = tx.Rollback(r.Context()) }()
	var result accountSummary
	var hash string
	err := tx.QueryRow(r.Context(), `SELECT id, name, privileges = 'admin', banned, registered, password FROM "user" WHERE id = $1 FOR UPDATE`, id).Scan(&result.ID, &result.Name, &result.Admin, &result.Disabled, &result.Registered, &hash)
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, 404, "User not found")
		return
	}
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	wasActiveAdmin, oldAdmin, oldDisabled := result.Admin && !result.Disabled, result.Admin, result.Disabled
	if body.Admin != nil {
		result.Admin = *body.Admin
	}
	if body.Disabled != nil {
		result.Disabled = *body.Disabled
	}
	if oldDisabled && !result.Disabled && !strings.HasPrefix(hash, "scrypt:") {
		writeError(w, 409, "Reset this account's password before reactivation")
		return
	}
	if wasActiveAdmin && (!result.Admin || result.Disabled) {
		var remaining int64
		if err := tx.QueryRow(r.Context(), `SELECT count(*) FROM "user" WHERE privileges = 'admin' AND NOT banned AND id <> $1`, id).Scan(&remaining); err != nil {
			writeError(w, 500, "Database unavailable")
			return
		}
		if remaining == 0 {
			writeError(w, 409, "Cannot disable or demote the last active administrator")
			return
		}
	}
	role := "user"
	if result.Admin {
		role = "admin"
	}
	if _, err := tx.Exec(r.Context(), `UPDATE "user" SET privileges = $1, banned = $2 WHERE id = $3`, role, result.Disabled, id); err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	if oldAdmin != result.Admin {
		if auditAccount(r.Context(), tx, actor.ID, id, "change_user_role") != nil {
			writeError(w, 500, "Database unavailable")
			return
		}
	}
	if oldDisabled != result.Disabled {
		action := "enable_user"
		if result.Disabled {
			action = "disable_user"
		}
		if auditAccount(r.Context(), tx, actor.ID, id, action) != nil {
			writeError(w, 500, "Database unavailable")
			return
		}
	}
	if tx.Commit(r.Context()) != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	writeJSON(w, 200, result)
}

func (a *application) resetUserPassword(w http.ResponseWriter, r *http.Request, actor user) {
	id, ok := userPathID(w, r)
	if ok {
		a.setAccountPassword(w, r, actor, id, false)
	}
}

func (a *application) changeOwnPassword(w http.ResponseWriter, r *http.Request, actor user) {
	a.setAccountPassword(w, r, actor, actor.ID, true)
}

func (a *application) setAccountPassword(w http.ResponseWriter, r *http.Request, actor user, id int32, own bool) {
	var body struct {
		Password        string `json:"password"`
		CurrentPassword string `json:"current_password"`
	}
	if !decodeAccountJSON(w, r, &body) {
		return
	}
	if !validNewPassword(body.Password) || (own && (body.CurrentPassword == "" || len(body.CurrentPassword) > 4096)) || (!own && body.CurrentPassword != "") {
		writeError(w, 422, "Password must be 14–256 characters without control characters; own changes require current password")
		return
	}
	hash, err := a.hashPassword(body.Password)
	if err != nil {
		writeError(w, 500, "Password hashing failed")
		return
	}
	tx, ok := a.beginAccountChange(w, r, actor, !own)
	if !ok {
		return
	}
	defer func() { _ = tx.Rollback(r.Context()) }()
	var previous string
	err = tx.QueryRow(r.Context(), `SELECT password FROM "user" WHERE id = $1 FOR UPDATE`, id).Scan(&previous)
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, 404, "User not found")
		return
	}
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	if own && !a.verifyPassword(previous, body.CurrentPassword) {
		writeError(w, 422, "Current password is incorrect")
		return
	}
	action := "reset_user_password"
	if own {
		action = "change_own_password"
	}
	if _, err := tx.Exec(r.Context(), `UPDATE "user" SET password = $1 WHERE id = $2`, hash, id); err != nil || auditAccount(r.Context(), tx, actor.ID, id, action) != nil || tx.Commit(r.Context()) != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (a *application) userProfile(w http.ResponseWriter, r *http.Request, _ user) {
	id, ok := userPathID(w, r)
	if !ok {
		return
	}
	var name string
	var registered time.Time
	var count int64
	err := a.pool.QueryRow(r.Context(), `SELECT name, registered, (SELECT count(*) FROM message WHERE from_user = u.id) FROM "user" u WHERE id = $1`, id).Scan(&name, &registered, &count)
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, 404, "User not found")
		return
	}
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	writeJSON(w, 200, map[string]any{"id": id, "name": name, "registered": registered, "comment_count": count})
}

type historyComment struct {
	comment
	ImageID   int32  `json:"image_id"`
	ImageName string `json:"image_name"`
}

func parseCommentCursor(value string) (time.Time, int32, error) {
	if len(value) > 100 {
		return time.Time{}, 0, errors.New("invalid cursor")
	}
	decoded, err := base64.RawURLEncoding.DecodeString(value)
	parts := strings.Split(string(decoded), ",")
	if err != nil || len(parts) != 2 {
		return time.Time{}, 0, errors.New("invalid cursor")
	}
	date, dateErr := time.Parse(time.RFC3339Nano, parts[0])
	id, idErr := strconv.ParseInt(parts[1], 10, 32)
	if dateErr != nil || idErr != nil || id < 1 {
		return time.Time{}, 0, errors.New("invalid cursor")
	}
	return date, int32(id), nil
}

func (a *application) userComments(w http.ResponseWriter, r *http.Request, _ user) {
	id, ok := userPathID(w, r)
	if !ok {
		return
	}
	limit := positiveInt(r.URL.Query().Get("limit"), 30)
	if limit > 100 {
		limit = 100
	}
	var before any
	var beforeID int32
	if cursor := r.URL.Query().Get("cursor"); cursor != "" {
		date, parsedID, err := parseCommentCursor(cursor)
		if err != nil {
			writeError(w, 422, "Invalid comment cursor")
			return
		}
		before, beforeID = date, parsedID
	}
	var exists bool
	if err := a.pool.QueryRow(r.Context(), `SELECT EXISTS (SELECT 1 FROM "user" WHERE id = $1)`, id).Scan(&exists); err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	if !exists {
		writeError(w, 404, "User not found")
		return
	}
	rows, err := a.pool.Query(r.Context(), `SELECT m.id, u.name, u.id, m.text, m.message_date, m.reply_to, i.id, i.name FROM message m JOIN "user" u ON u.id = m.from_user JOIN image i ON i.id = m.image WHERE m.from_user = $1 AND ($2::timestamptz IS NULL OR (m.message_date, m.id) < ($2::timestamptz, $3)) ORDER BY m.message_date DESC, m.id DESC LIMIT $4`, id, before, beforeID, limit+1)
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	defer rows.Close()
	items := []historyComment{}
	for rows.Next() {
		var item historyComment
		if err := rows.Scan(&item.ID, &item.Author, &item.AuthorID, &item.Text, &item.CreatedAt, &item.ReplyTo, &item.ImageID, &item.ImageName); err != nil {
			writeError(w, 500, "Database unavailable")
			return
		}
		items = append(items, item)
	}
	if rows.Err() != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	nextCursor := ""
	if len(items) > limit {
		items = items[:limit]
		last := items[len(items)-1]
		nextCursor = base64.RawURLEncoding.EncodeToString([]byte(last.CreatedAt.UTC().Format(time.RFC3339Nano) + "," + strconv.Itoa(int(last.ID))))
	}
	writeJSON(w, 200, map[string]any{"items": items, "next_cursor": nextCursor, "limit": limit})
}
