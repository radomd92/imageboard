package main

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/crypto/scrypt"
)

type config struct {
	databaseURL  string
	mediaRoot    string
	mediaURL     string
	healthToken  string
	staticRoot   string
	authTTL      time.Duration
	authCacheKey []byte
}

type user struct {
	ID    int32
	Name  string
	Admin bool
}

type cacheEntry struct {
	user    user
	expires time.Time
}

type application struct {
	pool      *pgxpool.Pool
	config    config
	cacheMu   sync.Mutex
	authCache map[string]cacheEntry
	scryptSem chan struct{}
}

type image struct {
	ID        int32     `json:"id"`
	Name      string    `json:"name"`
	Path      string    `json:"path"`
	MediaURL  string    `json:"media_url"`
	FileURL   string    `json:"file_url"`
	ThumbURL  string    `json:"thumbnail_url"`
	Kind      string    `json:"kind"`
	CreatedAt time.Time `json:"created_at"`
	FileSize  *int64    `json:"file_size"`
	Hits      int32     `json:"hits"`
	Uploader  *string   `json:"uploader"`
	Tags      []string  `json:"tags"`
	Comments  []comment `json:"comments"`
}

type comment struct {
	ID        int32     `json:"id"`
	Author    *string   `json:"author"`
	Text      string    `json:"text"`
	CreatedAt time.Time `json:"created_at"`
	ReplyTo   *int32    `json:"reply_to"`
}

type indexJob struct {
	ID         string     `json:"id"`
	Status     string     `json:"status"`
	CreatedAt  time.Time  `json:"created_at"`
	StartedAt  *time.Time `json:"started_at"`
	FinishedAt *time.Time `json:"finished_at"`
	MaxDepth   *int32     `json:"max_depth"`
	Discovered int64      `json:"discovered"`
	Processed  int64      `json:"processed"`
	Indexed    int64      `json:"indexed"`
	Updated    int64      `json:"updated"`
	Deindexed  int64      `json:"deindexed"`
	Skipped    int64      `json:"skipped"`
	Errors     int64      `json:"errors"`
	ErrorCode  *string    `json:"error_code"`
}

func main() {
	ctx := context.Background()
	cfg := loadConfig()
	pool, err := pgxpool.New(ctx, cfg.databaseURL)
	if err != nil {
		fatal(err)
	}
	defer pool.Close()
	if err := pool.Ping(ctx); err != nil {
		fatal(err)
	}
	app := &application{
		pool:      pool,
		config:    cfg,
		authCache: map[string]cacheEntry{},
		scryptSem: make(chan struct{}, envInt("AUTH_SCRYPT_CONCURRENCY", 4)),
	}
	server := &http.Server{
		Addr:              ":8000",
		Handler:           app.routes(),
		ReadHeaderTimeout: 10 * time.Second,
		IdleTimeout:       30 * time.Second,
	}
	if err := server.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
		fatal(err)
	}
}

func (a *application) routes() http.Handler {
	r := chi.NewRouter()
	r.Get("/health/live", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	r.Get("/health/ready", a.ready)
	r.Get("/", a.withAuth(a.index))
	r.Handle("/static/*", http.StripPrefix("/static/", http.FileServer(http.Dir(a.config.staticRoot))))
	r.Route("/api", func(r chi.Router) {
		r.Get("/internal/authorize", a.withAuth(a.authorizeMedia))
		r.Get("/me", a.withAuth(a.me))
		r.Get("/images", a.withAuth(a.listImages))
		r.Get("/tags", a.withAuth(a.listTags))
		r.Get("/dashboard", a.withAuth(a.dashboard))
		r.Get("/explore", a.withAdmin(a.explore))
		r.Post("/images/index", a.withAdmin(a.enqueueSingle))
		r.Post("/images/index-tree", a.withAdmin(a.enqueueTree))
		r.Post("/index-jobs", a.withAdmin(a.createJob))
		r.Get("/index-jobs/{id}", a.withAdmin(a.getJob))
		r.Post("/index-jobs/{id}/cancel", a.withAdmin(a.cancelJob))
		r.Get("/images/{id}", a.withAuth(a.getImage))
		r.Get("/images/{id}/file", a.withAuth(a.getImageFile))
		r.Post("/images/{id}/context", a.withAuth(a.contextUpdate))
		r.Patch("/images/{id}", a.withAdmin(a.updateImage))
		r.Post("/images/{id}/comments", a.withAuth(a.addComment))
	})
	return a.securityHeaders(r)
}

func (a *application) securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self'; connect-src 'self'")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		next.ServeHTTP(w, r)
	})
}

func (a *application) withAuth(handler func(http.ResponseWriter, *http.Request, user)) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		user, err := a.authenticate(r)
		if err != nil {
			w.Header().Set("WWW-Authenticate", `Basic`)
			writeError(w, http.StatusUnauthorized, "Authentication required")
			return
		}
		handler(w, r, user)
	}
}

func (a *application) withAdmin(handler func(http.ResponseWriter, *http.Request, user)) http.HandlerFunc {
	return a.withAuth(func(w http.ResponseWriter, r *http.Request, user user) {
		if !user.Admin {
			writeError(w, http.StatusForbidden, "Administrator access required")
			return
		}
		handler(w, r, user)
	})
}

func (a *application) authenticate(r *http.Request) (user, error) {
	username, password, ok := r.BasicAuth()
	if !ok || username == "" || password == "" {
		return user{}, errors.New("missing credentials")
	}
	key := a.authCacheKey(username, password)
	now := time.Now()
	a.cacheMu.Lock()
	entry, found := a.authCache[key]
	a.cacheMu.Unlock()
	if found && now.Before(entry.expires) {
		return entry.user, nil
	}
	var stored, privileges string
	var account user
	var banned bool
	err := a.pool.QueryRow(r.Context(), `SELECT id, name, password, privileges, banned FROM "user" WHERE name = $1`, username).Scan(&account.ID, &account.Name, &stored, &privileges, &banned)
	if err != nil || banned {
		return user{}, errors.New("invalid credentials")
	}
	account.Admin = privileges == "admin"
	if !a.verifyPassword(stored, password) {
		return user{}, errors.New("invalid credentials")
	}
	a.cacheMu.Lock()
	a.authCache[key] = cacheEntry{user: account, expires: now.Add(a.config.authTTL)}
	a.cacheMu.Unlock()
	return account, nil
}

func (a *application) authCacheKey(username, password string) string {
	mac := hmac.New(sha256.New, a.config.authCacheKey)
	mac.Write([]byte(username))
	mac.Write([]byte{0})
	mac.Write([]byte(password))
	return hex.EncodeToString(mac.Sum(nil))
}

func (a *application) verifyPassword(encoded, password string) bool {
	parts := strings.Split(encoded, "$")
	if len(parts) != 3 || !strings.HasPrefix(parts[0], "scrypt:") {
		return false
	}
	params := strings.Split(strings.TrimPrefix(parts[0], "scrypt:"), ":")
	if len(params) != 3 {
		return false
	}
	n, nErr := strconv.Atoi(params[0])
	r, rErr := strconv.Atoi(params[1])
	p, pErr := strconv.Atoi(params[2])
	digest, decodeErr := hex.DecodeString(parts[2])
	if nErr != nil || rErr != nil || pErr != nil || n < 2 || n > 32768 || r < 1 || r > 16 || p < 1 || p > 4 || decodeErr != nil {
		return false
	}
	a.scryptSem <- struct{}{}
	derived, err := scrypt.Key([]byte(password), []byte(parts[1]), n, r, p, len(digest))
	<-a.scryptSem
	return err == nil && subtle.ConstantTimeCompare(derived, digest) == 1
}

func (a *application) ready(w http.ResponseWriter, r *http.Request) {
	if !hmac.Equal([]byte(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")), []byte(a.config.healthToken)) || a.config.healthToken == "" {
		writeError(w, http.StatusNotFound, "Not found")
		return
	}
	if err := a.pool.Ping(r.Context()); err != nil {
		writeError(w, http.StatusServiceUnavailable, "Not ready")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (a *application) index(w http.ResponseWriter, r *http.Request, _ user) {
	http.ServeFile(w, r, filepath.Join(a.config.staticRoot, "index.html"))
}

func (a *application) me(w http.ResponseWriter, r *http.Request, user user) {
	writeJSON(w, http.StatusOK, map[string]any{
		"id":    user.ID,
		"name":  user.Name,
		"admin": user.Admin,
	})
}

func (a *application) authorizeMedia(w http.ResponseWriter, r *http.Request, user user) {
	original, err := url.PathUnescape(strings.Split(r.Header.Get("X-Original-URI"), "?")[0])
	if err != nil {
		writeError(w, http.StatusForbidden, "Forbidden")
		return
	}
	if !strings.HasPrefix(original, "/media/") && !strings.HasPrefix(original, "/thumbnail/") {
		w.WriteHeader(http.StatusNoContent)
		return
	}
	path := ""
	if strings.HasPrefix(original, "/media/") {
		path = strings.ReplaceAll(strings.TrimPrefix(original, "/media/"), "/", "$")
	} else {
		parts := strings.Split(strings.TrimPrefix(original, "/thumbnail/"), "/")
		if len(parts) < 2 {
			writeError(w, http.StatusForbidden, "Forbidden")
			return
		}
		path = strings.Join(parts[:len(parts)-1], "$")
	}
	if !user.Admin {
		var id int32
		if err := a.pool.QueryRow(r.Context(), "SELECT id FROM image WHERE image_path = $1", path).Scan(&id); err != nil {
			writeError(w, http.StatusForbidden, "Media is not indexed")
			return
		}
	}
	w.WriteHeader(http.StatusNoContent)
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func writeError(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

func fatal(err error) {
	// Configuration and database errors may embed secrets; never emit their text.
	_, _ = fmt.Fprintln(os.Stderr, "startup failed")
	_ = err
	os.Exit(1)
}

func loadConfig() config {
	secret := os.Getenv("IMAGEBOARD_SECRET_KEY")
	if secret == "" {
		secret = randomID()
	}
	return config{
		databaseURL:  normalizeDatabaseURL(requiredEnv("IMAGEBOARD_DATABASE_URL")),
		mediaRoot:    requiredEnv("IMAGEBOARD_MEDIA_ROOT"),
		mediaURL:     env("IMAGEBOARD_MEDIA_URL", "/media"),
		healthToken:  os.Getenv("IMAGEBOARD_HEALTH_TOKEN"),
		staticRoot:   env("IMAGEBOARD_STATIC_ROOT", "/static"),
		authTTL:      time.Duration(envInt("AUTH_CACHE_SECONDS", 20)) * time.Second,
		authCacheKey: []byte(secret),
	}
}

func requiredEnv(name string) string {
	value := os.Getenv(name)
	if value == "" {
		fatal(errors.New("missing configuration"))
	}
	return value
}

func env(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func envInt(name string, fallback int) int {
	value, err := strconv.Atoi(os.Getenv(name))
	if err != nil || value < 1 {
		return fallback
	}
	return value
}

func normalizeDatabaseURL(value string) string {
	return strings.Replace(value, "postgresql+psycopg://", "postgres://", 1)
}

func randomID() string {
	bytes := make([]byte, 16)
	_, _ = rand.Read(bytes)
	return hex.EncodeToString(bytes)
}

func uuid() string {
	bytes := make([]byte, 16)
	_, _ = rand.Read(bytes)
	bytes[6] = bytes[6]&0x0f | 0x40
	bytes[8] = bytes[8]&0x3f | 0x80
	encoded := hex.EncodeToString(bytes)
	return encoded[0:8] + "-" + encoded[8:12] + "-" + encoded[12:16] + "-" + encoded[16:20] + "-" + encoded[20:]
}
