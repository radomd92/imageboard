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
	databaseURL            string
	mediaRoot              string
	mediaURL               string
	healthToken            string
	staticRoot             string
	authTTL                time.Duration
	authCacheKey           []byte
	thumbnailEncryptionKey [32]byte
	thumbnailCacheKey      [32]byte
}

type user struct {
	ID    int32
	Name  string
	Admin bool
}

type cacheEntry struct {
	user    user
	hash    string
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
	Favorite  bool      `json:"favorite"`
}

type comment struct {
	ID        int32     `json:"id"`
	Author    *string   `json:"author"`
	AuthorID  *int32    `json:"author_id"`
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
		Addr:              env("IMAGEBOARD_LISTEN_ADDR", ":8000"),
		Handler:           app.routes(),
		ReadHeaderTimeout: 10 * time.Second,
		IdleTimeout:       30 * time.Second,
	}
	if err := server.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
		fatal(err)
	}
}

func (a *application) routes() http.Handler {
	router := chi.NewRouter()
	router.Get("/health/live", func(response http.ResponseWriter, _ *http.Request) {
		writeJSON(response, http.StatusOK, map[string]string{"status": "ok"})
	})
	router.Get("/health/ready", a.ready)
	router.Get("/", a.withAuth(a.index))
	router.Get("/thumbnail/*", a.withAuth(a.thumbnail))
	router.Method(http.MethodHead, "/thumbnail/*", a.withAuth(a.thumbnail))
	router.Handle("/static/*", http.StripPrefix("/static/", http.FileServer(http.Dir(a.config.staticRoot))))
	router.Route("/api", func(apiRouter chi.Router) {
		apiRouter.Get("/internal/authorize", a.withAuth(a.authorizeMedia))
		apiRouter.Get("/me", a.withAuth(a.me))
		apiRouter.Put("/me/password", a.accountWrite(a.withAuth(a.changeOwnPassword)))
		apiRouter.Get("/admin/users", a.withAdmin(a.listUsers))
		apiRouter.Post("/admin/users", a.accountWrite(a.withAdmin(a.createUser)))
		apiRouter.Patch("/admin/users/{id}", a.accountWrite(a.withAdmin(a.updateUser)))
		apiRouter.Put("/admin/users/{id}/password", a.accountWrite(a.withAdmin(a.resetUserPassword)))
		apiRouter.Get("/users/{id}", a.withAuth(a.userProfile))
		apiRouter.Get("/users/{id}/comments", a.withAuth(a.userComments))
		apiRouter.Get("/images", a.withAuth(a.listImages))
		apiRouter.Get("/images/untagged", a.withAuth(a.listUntaggedImages))
		apiRouter.Get("/tags", a.withAuth(a.listTags))
		apiRouter.Get("/dashboard", a.withAuth(a.dashboard))
		apiRouter.Get("/explore", a.withAdmin(a.explore))
		apiRouter.Get("/documents/read", a.withAdmin(a.readDocument))
		apiRouter.Post("/images/index", a.withAdmin(a.enqueueSingle))
		apiRouter.Post("/images/index-tree", a.withAdmin(a.enqueueTree))
		apiRouter.Post("/index-jobs", a.withAdmin(a.createJob))
		apiRouter.Get("/index-jobs/{id}", a.withAdmin(a.getJob))
		apiRouter.Post("/index-jobs/{id}/cancel", a.withAdmin(a.cancelJob))
		apiRouter.Get("/images/{id}", a.withAuth(a.getImage))
		apiRouter.Get("/images/{id}/similar", a.withAuth(a.similarImages))
		apiRouter.Put("/images/{id}/favorite", a.withAuth(a.favoriteImage))
		apiRouter.Delete("/images/{id}/favorite", a.withAuth(a.unfavoriteImage))
		apiRouter.Get("/images/{id}/file", a.withAuth(a.getImageFile))
		apiRouter.Post("/images/{id}/context", a.withAuth(a.contextUpdate))
		apiRouter.Patch("/images/{id}", a.withAdmin(a.updateImage))
		apiRouter.Post("/images/{id}/comments", a.withAuth(a.addComment))
	})
	return a.securityHeaders(router)
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
	var stored, privileges string
	var account user
	var banned bool
	err := a.pool.QueryRow(r.Context(), `SELECT id, name, password, privileges, banned FROM "user" WHERE name = $1`, username).Scan(&account.ID, &account.Name, &stored, &privileges, &banned)
	if err != nil || banned {
		return user{}, errors.New("invalid credentials")
	}
	account.Admin = privileges == "admin"
	if found && now.Before(entry.expires) && entry.hash == stored && entry.user.ID == account.ID {
		return account, nil
	}
	if !a.verifyPassword(stored, password) {
		return user{}, errors.New("invalid credentials")
	}
	a.cacheMu.Lock()
	// Expired proofs need not accumulate as passwords are rotated.
	for cachedKey, cached := range a.authCache {
		if !now.Before(cached.expires) {
			delete(a.authCache, cachedKey)
		}
	}
	a.authCache[key] = cacheEntry{user: account, hash: stored, expires: now.Add(a.config.authTTL)}
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
	cost, costErr := strconv.Atoi(params[0])
	blockSize, blockSizeErr := strconv.Atoi(params[1])
	parallelism, parallelismErr := strconv.Atoi(params[2])
	digest, decodeErr := hex.DecodeString(parts[2])
	if costErr != nil || blockSizeErr != nil || parallelismErr != nil || cost < 2 || cost > 32768 || blockSize < 1 || blockSize > 16 || parallelism < 1 || parallelism > 4 || decodeErr != nil || len(digest) != 64 || len(parts[1]) < 1 || len(parts[1]) > 128 {
		return false
	}
	a.scryptSem <- struct{}{}
	derived, err := scrypt.Key([]byte(password), []byte(parts[1]), cost, blockSize, parallelism, len(digest))
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
	secret := requiredEnv("IMAGEBOARD_SECRET_KEY")
	return config{
		databaseURL:            normalizeDatabaseURL(requiredEnv("IMAGEBOARD_DATABASE_URL")),
		mediaRoot:              requiredEnv("IMAGEBOARD_MEDIA_ROOT"),
		mediaURL:               env("IMAGEBOARD_MEDIA_URL", "/media"),
		healthToken:            os.Getenv("IMAGEBOARD_HEALTH_TOKEN"),
		staticRoot:             env("IMAGEBOARD_STATIC_ROOT", "/static"),
		authTTL:                time.Duration(envInt("AUTH_CACHE_SECONDS", 20)) * time.Second,
		authCacheKey:           []byte(secret),
		thumbnailEncryptionKey: derivedKey(secret, "thumbnail encryption v1"),
		thumbnailCacheKey:      derivedKey(secret, "thumbnail cache key v1"),
	}
}

func derivedKey(secret, label string) [32]byte {
	mac := hmac.New(sha256.New, []byte(secret))
	_, _ = mac.Write([]byte(label))
	var key [32]byte
	copy(key[:], mac.Sum(nil))
	return key
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

func uuid() string {
	randomBytes := make([]byte, 16)
	_, _ = rand.Read(randomBytes)
	randomBytes[6] = randomBytes[6]&0x0f | 0x40
	randomBytes[8] = randomBytes[8]&0x3f | 0x80
	encoded := hex.EncodeToString(randomBytes)
	return encoded[0:8] + "-" + encoded[8:12] + "-" + encoded[12:16] + "-" + encoded[16:20] + "-" + encoded[20:]
}
