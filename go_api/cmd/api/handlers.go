package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"io/fs"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

const (
	maxCommentTextBytes = 8 * 1024
	// JSON escaping can triple UTF-8 size; leave room for tags and replies.
	maxCommentRequestBytes = 48 * 1024
)

func (a *application) listImages(w http.ResponseWriter, r *http.Request, currentUser user) {
	query := r.URL.Query()
	search, err := parseImageSearch(query.Get("q"))
	tagName := query.Get("tag")
	if err != nil || len(tagName) > 100 {
		writeError(w, http.StatusUnprocessableEntity, "Invalid query")
		return
	}
	page := positiveInt(query.Get("page"), 1)
	limit := positiveInt(query.Get("limit"), 30)
	if limit > 100000 {
		limit = 100000
	}
	filters := []string{"TRUE"}
	arguments := []any{}
	addArgument := func(value any) string {
		arguments = append(arguments, value)
		return "$" + strconv.Itoa(len(arguments))
	}
	if search.root != nil {
		filters = append(filters, compileImageSearch(search.root, addArgument))
	}
	if tagName != "" {
		placeholder := addArgument(normalizeSearchTerm(tagName))
		filters = append(filters, "EXISTS (SELECT 1 FROM tag_image ti JOIN tag t ON t.id = ti.tag WHERE ti.image = i.id AND translate(lower(t.name), '_', ' ') = "+placeholder+")")
	}
	if query.Get("untagged") == "true" {
		filters = append(filters, "NOT EXISTS (SELECT 1 FROM tag_image ti WHERE ti.image = i.id)")
	}
	if query.Get("favorite") == "true" {
		placeholder := addArgument(currentUser.ID)
		filters = append(filters, "EXISTS (SELECT 1 FROM image_favorite favorite WHERE favorite.image_id = i.id AND favorite.user_id = "+placeholder+")")
	}
	whereClause := strings.Join(filters, " AND ")
	var total int64
	if err := a.pool.QueryRow(r.Context(), "SELECT count(*) FROM image i WHERE "+whereClause, arguments...).Scan(&total); err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	arguments = append(arguments, limit, (page-1)*limit)
	rows, err := a.pool.Query(r.Context(), `SELECT i.id, i.name, i.image_path, i.created_date, i.file_size, i.hits, u.name
FROM image i LEFT JOIN "user" u ON u.id = i.uploader WHERE `+whereClause+` ORDER BY i.created_date DESC, i.id DESC LIMIT $`+strconv.Itoa(len(arguments)-1)+` OFFSET $`+strconv.Itoa(len(arguments)), arguments...)
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	images, err := a.scanImages(r.Context(), rows, currentUser.ID)
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": images, "page": page, "limit": limit, "total": total})
}

func (a *application) listUntaggedImages(w http.ResponseWriter, r *http.Request, currentUser user) {
	request := r.Clone(r.Context())
	url := *r.URL
	request.URL = &url
	query := request.URL.Query()
	query.Set("untagged", "true")
	query.Set("limit", "100000")
	request.URL.RawQuery = query.Encode()
	a.listImages(w, request, currentUser)
}

type imageSearch struct {
	root *imageSearchNode
}

type imageSearchNodeKind uint8

const (
	imageSearchText imageSearchNodeKind = iota
	imageSearchTag
	imageSearchPath
	imageSearchComment
	imageSearchAnd
	imageSearchOr
	imageSearchNot
)

type imageSearchNode struct {
	kind        imageSearchNodeKind
	value       string
	left, right *imageSearchNode
}

type imageSearchParser struct {
	value string
	pos   int
	terms int
}

func parseImageSearch(value string) (imageSearch, error) {
	if len(value) > 1000 {
		return imageSearch{}, errors.New("query too long")
	}
	parser := imageSearchParser{value: value}
	parser.skipSpace()
	if parser.pos == len(value) {
		return imageSearch{}, nil
	}
	root, err := parser.parseOr()
	if err != nil {
		return imageSearch{}, err
	}
	parser.skipSpace()
	if parser.pos != len(value) {
		return imageSearch{}, errors.New("invalid query term")
	}
	return imageSearch{root: root}, nil
}

func (p *imageSearchParser) parseOr() (*imageSearchNode, error) {
	left, err := p.parseAnd()
	if err != nil {
		return nil, err
	}
	for {
		p.skipSpace()
		if !p.consume('|') {
			return left, nil
		}
		right, err := p.parseAnd()
		if err != nil {
			return nil, err
		}
		left = &imageSearchNode{kind: imageSearchOr, left: left, right: right}
	}
}

func (p *imageSearchParser) parseAnd() (*imageSearchNode, error) {
	left, err := p.parseUnary()
	if err != nil {
		return nil, err
	}
	for {
		p.skipSpace()
		if p.peek() == '|' || p.peek() == ')' || p.pos == len(p.value) {
			return left, nil
		}
		p.consume('+')
		right, err := p.parseUnary()
		if err != nil {
			return nil, err
		}
		left = &imageSearchNode{kind: imageSearchAnd, left: left, right: right}
	}
}

func (p *imageSearchParser) parseUnary() (*imageSearchNode, error) {
	p.skipSpace()
	if p.consume('!') {
		term, err := p.parsePrimary()
		if err != nil {
			return nil, err
		}
		if term.kind != imageSearchTag && term.kind != imageSearchPath && term.kind != imageSearchComment {
			return nil, errors.New("negation requires a tag, comment, or path term")
		}
		return &imageSearchNode{kind: imageSearchNot, left: term}, nil
	}
	return p.parsePrimary()
}

func (p *imageSearchParser) parsePrimary() (*imageSearchNode, error) {
	p.skipSpace()
	if p.consume('(') {
		node, err := p.parseOr()
		if err != nil {
			return nil, err
		}
		p.skipSpace()
		if !p.consume(')') {
			return nil, errors.New("unterminated query group")
		}
		return node, nil
	}
	if p.pos == len(p.value) || p.peek() == ')' || p.peek() == '|' || p.peek() == '+' {
		return nil, errors.New("missing query term")
	}

	kind := imageSearchText
	term := ""
	switch p.peek() {
	case '#':
		p.pos++
		start := p.pos
		for p.pos < len(p.value) && !p.delimiter() {
			p.pos++
		}
		var err error
		term, err = cleanTag(normalizeSearchTerm(p.value[start:p.pos]))
		if err != nil {
			return nil, err
		}
		kind = imageSearchTag
	case '[', '\'':
		opening := p.peek()
		closing := byte(']')
		if opening == '\'' {
			closing = '\''
		}
		p.pos++
		end := strings.IndexByte(p.value[p.pos:], closing)
		if end < 0 {
			return nil, errors.New("unterminated query term")
		}
		term = normalizeSearchTerm(p.value[p.pos : p.pos+end])
		p.pos += end + 1
		if term == "" || len(term) > 100 {
			return nil, errors.New("invalid query term")
		}
		if opening == '[' {
			kind = imageSearchComment
		} else {
			kind = imageSearchPath
		}
	default:
		start := p.pos
		for p.pos < len(p.value) && !p.delimiter() {
			p.pos++
		}
		term = normalizeSearchTerm(p.value[start:p.pos])
		if term == "" || len(term) > 100 {
			return nil, errors.New("invalid query term")
		}
	}
	p.terms++
	if p.terms > 20 {
		return nil, errors.New("too many query terms")
	}
	return &imageSearchNode{kind: kind, value: term}, nil
}

func (p *imageSearchParser) skipSpace() {
	for p.pos < len(p.value) && unicode.IsSpace(rune(p.value[p.pos])) {
		p.pos++
	}
}

func (p *imageSearchParser) peek() byte {
	if p.pos == len(p.value) {
		return 0
	}
	return p.value[p.pos]
}

func (p *imageSearchParser) consume(value byte) bool {
	if p.peek() != value {
		return false
	}
	p.pos++
	return true
}

func (p *imageSearchParser) delimiter() bool {
	return unicode.IsSpace(rune(p.value[p.pos])) || strings.ContainsRune("!#+|()", rune(p.value[p.pos]))
}

func compileImageSearch(node *imageSearchNode, addArgument func(any) string) string {
	switch node.kind {
	case imageSearchText:
		placeholder := addArgument(node.value)
		return "(translate(lower(i.name), '_', ' ') LIKE '%' || " + placeholder + " || '%' OR translate(lower(i.image_path), '_', ' ') LIKE '%' || " + placeholder + " || '%')"
	case imageSearchTag:
		placeholder := addArgument(node.value)
		return "EXISTS (SELECT 1 FROM tag_image ti JOIN tag t ON t.id = ti.tag WHERE ti.image = i.id AND translate(lower(t.name), '_', ' ') = " + placeholder + ")"
	case imageSearchPath:
		placeholder := addArgument(node.value)
		return "translate(lower(i.image_path), '_', ' ') LIKE '%' || " + placeholder + " || '%'"
	case imageSearchComment:
		placeholder := addArgument(node.value)
		return "EXISTS (SELECT 1 FROM message m WHERE m.image = i.id AND translate(lower(m.text), '_', ' ') LIKE '%' || " + placeholder + " || '%')"
	case imageSearchNot:
		return "NOT (" + compileImageSearch(node.left, addArgument) + ")"
	case imageSearchAnd:
		return "(" + compileImageSearch(node.left, addArgument) + " AND " + compileImageSearch(node.right, addArgument) + ")"
	case imageSearchOr:
		return "(" + compileImageSearch(node.left, addArgument) + " OR " + compileImageSearch(node.right, addArgument) + ")"
	default:
		return "FALSE"
	}
}

func normalizeSearchTerm(value string) string {
	return strings.ToLower(strings.TrimSpace(strings.ReplaceAll(value, "_", " ")))
}

func (a *application) getImage(w http.ResponseWriter, r *http.Request, currentUser user) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	image, err := a.imageByID(r.Context(), id, currentUser.ID)
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, 404, "Image not found")
		return
	}
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	writeJSON(w, http.StatusOK, image)
}

func (a *application) imageByID(ctx context.Context, id, userID int32) (image, error) {
	rows, err := a.pool.Query(ctx, `SELECT i.id, i.name, i.image_path, i.created_date, i.file_size, i.hits, u.name
FROM image i LEFT JOIN "user" u ON u.id = i.uploader WHERE i.id = $1`, id)
	if err != nil {
		return image{}, err
	}
	images, err := a.scanImages(ctx, rows, userID)
	if err != nil {
		return image{}, err
	}
	if len(images) == 0 {
		return image{}, pgx.ErrNoRows
	}
	return images[0], nil
}

func (a *application) scanImages(ctx context.Context, rows pgx.Rows, userID int32) ([]image, error) {
	defer rows.Close()
	images := []image{}
	imageIDs := []int32{}
	for rows.Next() {
		var item image
		if err := rows.Scan(&item.ID, &item.Name, &item.Path, &item.CreatedAt, &item.FileSize, &item.Hits, &item.Uploader); err != nil {
			return nil, err
		}
		item.MediaURL = a.mediaPath(item.Path)
		item.FileURL = "/api/images/" + strconv.Itoa(int(item.ID)) + "/file"
		item.Kind = mediaKind(item.Path)
		item.ThumbURL = "/thumbnail/" + encodedPath(item.Path) + "/small"
		item.Tags, item.Comments = []string{}, []comment{}
		images, imageIDs = append(images, item), append(imageIDs, item.ID)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(images) == 0 {
		return images, nil
	}
	imagesByID := map[int32]*image{}
	for i := range images {
		imagesByID[images[i].ID] = &images[i]
	}
	tagRows, err := a.pool.Query(ctx, `SELECT ti.image, t.name FROM tag_image ti JOIN tag t ON t.id = ti.tag WHERE ti.image = ANY($1) ORDER BY t.name`, imageIDs)
	if err != nil {
		return nil, err
	}
	for tagRows.Next() {
		var imageID int32
		var tagName string
		if err := tagRows.Scan(&imageID, &tagName); err != nil {
			tagRows.Close()
			return nil, err
		}
		imagesByID[imageID].Tags = append(imagesByID[imageID].Tags, tagName)
	}
	if err := tagRows.Err(); err != nil {
		tagRows.Close()
		return nil, err
	}
	tagRows.Close()
	commentRows, err := a.pool.Query(ctx, `SELECT m.image, m.id, u.name, u.id, m.text, m.message_date, m.reply_to
FROM message m LEFT JOIN "user" u ON u.id = m.from_user WHERE m.image = ANY($1) ORDER BY m.message_date, m.id`, imageIDs)
	if err != nil {
		return nil, err
	}
	for commentRows.Next() {
		var imageID int32
		var item comment
		if err := commentRows.Scan(&imageID, &item.ID, &item.Author, &item.AuthorID, &item.Text, &item.CreatedAt, &item.ReplyTo); err != nil {
			commentRows.Close()
			return nil, err
		}
		imagesByID[imageID].Comments = append(imagesByID[imageID].Comments, item)
	}
	if err := commentRows.Err(); err != nil {
		commentRows.Close()
		return nil, err
	}
	commentRows.Close()

	favoriteRows, err := a.pool.Query(ctx, "SELECT image_id FROM image_favorite WHERE user_id = $1 AND image_id = ANY($2)", userID, imageIDs)
	if err != nil {
		return nil, err
	}
	for favoriteRows.Next() {
		var imageID int32
		if err := favoriteRows.Scan(&imageID); err != nil {
			favoriteRows.Close()
			return nil, err
		}
		imagesByID[imageID].Favorite = true
	}
	if err := favoriteRows.Err(); err != nil {
		favoriteRows.Close()
		return nil, err
	}
	favoriteRows.Close()
	return images, nil
}

func (a *application) listTags(w http.ResponseWriter, r *http.Request, _ user) {
	rows, err := a.pool.Query(r.Context(), `SELECT t.name, count(ti.image), max(ti.image) FROM tag t JOIN tag_image ti ON ti.tag = t.id GROUP BY t.id, t.name ORDER BY count(ti.image) DESC, t.name`)
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	defer rows.Close()
	result := []map[string]any{}
	for rows.Next() {
		var name string
		var count int64
		var imageID int32
		if err := rows.Scan(&name, &count, &imageID); err != nil {
			writeError(w, 500, "Database unavailable")
			return
		}
		result = append(result, map[string]any{"name": name, "count": count, "image_id": imageID})
	}
	writeJSON(w, 200, result)
}

func (a *application) dashboard(w http.ResponseWriter, r *http.Request, currentUser user) {
	var total, untagged int64
	if err := a.pool.QueryRow(r.Context(), "SELECT count(*) FROM image").Scan(&total); err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	if err := a.pool.QueryRow(r.Context(), "SELECT count(*) FROM image i WHERE NOT EXISTS (SELECT 1 FROM tag_image ti WHERE ti.image = i.id)").Scan(&untagged); err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	rows, err := a.pool.Query(r.Context(), `SELECT t.name, count(*) FROM tag t JOIN tag_image ti ON ti.tag = t.id JOIN image_hits h ON h.image_id = ti.image WHERE h.hit_date >= NOW() - INTERVAL '30 days' GROUP BY t.id, t.name ORDER BY count(*) DESC LIMIT 8`)
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	defer rows.Close()
	tags := []map[string]any{}
	for rows.Next() {
		var name string
		var hits int64
		if err := rows.Scan(&name, &hits); err != nil {
			writeError(w, 500, "Database unavailable")
			return
		}
		tags = append(tags, map[string]any{"name": name, "hits": hits})
	}
	if rows.Err() != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	rows.Close()
	rankings, err := a.rankedImages(r.Context(), currentUser)
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	writeJSON(w, 200, map[string]any{"total": total, "untagged": untagged, "popular_tags": tags,
		"most_viewed": rankings["most_viewed"], "most_commented": rankings["most_commented"], "most_favorited": rankings["most_favorited"]})
}

func (a *application) explore(w http.ResponseWriter, r *http.Request, _ user) {
	canonical, err := canonicalPath(r.URL.Query().Get("path"), true)
	if err != nil {
		writeError(w, 400, "Invalid directory path")
		return
	}
	directory, err := a.existingPath(canonical)
	if err != nil || !directory.info.IsDir() {
		writeError(w, 404, "Directory not found")
		return
	}
	entries, err := os.ReadDir(directory.path)
	if err != nil {
		if errors.Is(err, fs.ErrPermission) {
			writeError(w, 403, "Directory is not readable")
		} else {
			writeError(w, 404, "Directory is not available")
		}
		return
	}
	type entry struct {
		Name         string  `json:"name"`
		Path         string  `json:"path"`
		Type         string  `json:"type"`
		MediaURL     *string `json:"media_url"`
		ThumbnailURL *string `json:"thumbnail_url"`
		Size         *int64  `json:"size"`
		Indexed      bool    `json:"indexed"`
	}
	result := []entry{}
	mediaPaths := []string{}
	for _, directoryEntry := range entries {
		if !safeComponent(directoryEntry.Name()) || directoryEntry.Type()&os.ModeSymlink != 0 {
			continue
		}
		info, infoErr := directoryEntry.Info()
		if infoErr != nil {
			continue
		}
		path := joinCanonical(canonical, directoryEntry.Name())
		if directoryEntry.IsDir() {
			result = append(result, entry{Name: directoryEntry.Name(), Path: path, Type: "directory"})
			continue
		}
		if !info.Mode().IsRegular() {
			continue
		}
		if supportedDocument(directoryEntry.Name()) {
			result = append(result, entry{Name: directoryEntry.Name(), Path: path, Type: "document"})
			continue
		}
		if !supportedMedia(directoryEntry.Name()) {
			continue
		}
		kind, size := mediaKind(directoryEntry.Name()), info.Size()
		media := a.mediaPath(path)
		thumb := "/thumbnail/" + encodedPath(path) + "/small"
		result = append(result, entry{Name: directoryEntry.Name(), Path: path, Type: kind, MediaURL: &media, ThumbnailURL: &thumb, Size: &size})
		mediaPaths = append(mediaPaths, path)
	}
	indexed := map[string]bool{}
	if len(mediaPaths) > 0 {
		rows, queryErr := a.pool.Query(r.Context(), "SELECT image_path FROM image WHERE image_path = ANY($1)", mediaPaths)
		if queryErr != nil {
			writeError(w, 500, "Database unavailable")
			return
		}
		for rows.Next() {
			var path string
			if rows.Scan(&path) == nil {
				indexed[path] = true
			}
		}
		rows.Close()
	}
	for i := range result {
		result[i].Indexed = indexed[result[i].Path]
	}
	sort.Slice(result, func(i, j int) bool {
		if result[i].Type == "directory" && result[j].Type != "directory" {
			return true
		}
		if result[i].Type != "directory" && result[j].Type == "directory" {
			return false
		}
		return strings.ToLower(result[i].Name) < strings.ToLower(result[j].Name)
	})
	writeJSON(w, 200, map[string]any{"path": canonical, "entries": result})
}

const maxDocumentBytes = 1 << 20

// readDocument returns source text only. The browser never receives HTML as a document response.
func (a *application) readDocument(w http.ResponseWriter, r *http.Request, _ user) {
	requestedPath := r.URL.Query().Get("path")
	if len(requestedPath) > 4096 {
		writeError(w, http.StatusUnprocessableEntity, "Invalid document path")
		return
	}
	canonicalPath, err := canonicalPath(requestedPath, false)
	if err != nil {
		writeError(w, http.StatusUnprocessableEntity, "Invalid document path")
		return
	}
	document, err := a.existingPath(canonicalPath)
	if err != nil || !document.info.Mode().IsRegular() || !supportedDocument(document.info.Name()) {
		writeError(w, http.StatusNotFound, "Document not found")
		return
	}
	file, err := os.Open(document.path)
	if err != nil {
		writeError(w, http.StatusNotFound, "Document not found")
		return
	}
	defer func() { _ = file.Close() }()
	content, err := io.ReadAll(io.LimitReader(file, maxDocumentBytes+1))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Unable to read document")
		return
	}
	truncated := len(content) > maxDocumentBytes
	if truncated {
		content = content[:maxDocumentBytes]
	}
	if !utf8.Valid(content) {
		writeError(w, http.StatusUnprocessableEntity, "Document is not UTF-8 text")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"path":      canonicalPath,
		"content":   string(content),
		"truncated": truncated,
	})
}

func (a *application) enqueueSingle(w http.ResponseWriter, r *http.Request, user user) {
	var body struct {
		Path string `json:"path"`
	}
	if !decodeJSON(w, r, &body) {
		return
	}
	if !supportedMedia(filepath.Base(body.Path)) {
		writeError(w, http.StatusUnsupportedMediaType, "Unsupported media type")
		return
	}
	job, err := a.enqueueJob(r.Context(), user, body.Path, int32Pointer(0))
	if err != nil {
		writeError(w, http.StatusBadRequest, "Invalid media path")
		return
	}
	writeJSON(w, 202, job)
}
func (a *application) enqueueTree(w http.ResponseWriter, r *http.Request, user user) {
	job, err := a.enqueueJob(r.Context(), user, "", nil)
	if err != nil {
		writeError(w, 500, "Unable to queue index job")
		return
	}
	writeJSON(w, 202, job)
}
func (a *application) createJob(w http.ResponseWriter, r *http.Request, user user) {
	var body struct {
		Path     string `json:"path"`
		MaxDepth *int32 `json:"max_depth"`
	}
	if !decodeJSON(w, r, &body) {
		return
	}
	if body.MaxDepth != nil && (*body.MaxDepth < 0 || *body.MaxDepth > 128) {
		writeError(w, 422, "Invalid index depth")
		return
	}
	job, err := a.enqueueJob(r.Context(), user, body.Path, body.MaxDepth)
	if err != nil {
		writeError(w, http.StatusBadRequest, "Invalid media path")
		return
	}
	writeJSON(w, 202, job)
}

func (a *application) enqueueJob(ctx context.Context, user user, path string, maxDepth *int32) (indexJob, error) {
	canonical, err := canonicalPath(path, true)
	if err != nil {
		return indexJob{}, err
	}
	id := uuid()
	row := a.pool.QueryRow(ctx, `INSERT INTO index_job (id, root_path, max_depth, status, requested_by, created_at, discovered, processed, indexed, updated, deindexed, skipped, errors) VALUES ($1::uuid, $2, $3, 'pending', $4, NOW(), 0, 0, 0, 0, 0, 0, 0) RETURNING `+jobColumns, id, canonical, maxDepth, user.ID)
	job, err := scanJob(row)
	if err == nil {
		return job, nil
	}
	var pgErr *pgconn.PgError
	if !errors.As(err, &pgErr) || pgErr.Code != "23505" {
		return indexJob{}, err
	}
	return a.activeJob(ctx)
}

const jobColumns = "id::text, status, created_at, started_at, finished_at, max_depth, discovered, processed, indexed, updated, deindexed, skipped, errors, error_code"

func scanJob(row pgx.Row) (indexJob, error) {
	var job indexJob
	err := row.Scan(
		&job.ID,
		&job.Status,
		&job.CreatedAt,
		&job.StartedAt,
		&job.FinishedAt,
		&job.MaxDepth,
		&job.Discovered,
		&job.Processed,
		&job.Indexed,
		&job.Updated,
		&job.Deindexed,
		&job.Skipped,
		&job.Errors,
		&job.ErrorCode,
	)
	return job, err
}

func (a *application) activeJob(ctx context.Context) (indexJob, error) {
	return scanJob(a.pool.QueryRow(
		ctx,
		"SELECT "+jobColumns+" FROM index_job WHERE status IN ('pending', 'running') ORDER BY created_at LIMIT 1",
	))
}

func (a *application) getJob(w http.ResponseWriter, r *http.Request, _ user) {
	job, err := a.job(r.Context(), chi.URLParam(r, "id"))
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, 404, "Index job not found")
	} else if err != nil {
		writeError(w, 500, "Database unavailable")
	} else {
		writeJSON(w, 200, job)
	}
}

func (a *application) cancelJob(w http.ResponseWriter, r *http.Request, _ user) {
	id := chi.URLParam(r, "id")
	_, err := a.pool.Exec(
		r.Context(),
		"UPDATE index_job SET status = 'cancelled', finished_at = NOW() WHERE id = $1::uuid AND status IN ('pending', 'running')",
		id,
	)
	if err != nil {
		writeError(w, 404, "Index job not found")
		return
	}
	job, err := a.job(r.Context(), id)
	if err != nil {
		writeError(w, 404, "Index job not found")
		return
	}
	writeJSON(w, 200, job)
}

func (a *application) job(ctx context.Context, id string) (indexJob, error) {
	return scanJob(a.pool.QueryRow(ctx, "SELECT "+jobColumns+" FROM index_job WHERE id = $1::uuid", id))
}

func (a *application) getImageFile(w http.ResponseWriter, r *http.Request, user user) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	var path string
	if err := a.pool.QueryRow(r.Context(), "SELECT image_path FROM image WHERE id = $1", id).Scan(&path); errors.Is(err, pgx.ErrNoRows) {
		writeError(w, 404, "Image not found")
		return
	} else if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	if _, err := a.existingPath(path); err != nil {
		_, _ = a.enqueueJob(r.Context(), user, path, int32Pointer(0))
		writeError(w, 404, "Media file not found")
		return
	}
	if _, err := a.pool.Exec(r.Context(), "UPDATE image SET hits = hits + 1 WHERE id = $1", id); err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	_, _ = a.pool.Exec(r.Context(), "INSERT INTO image_hits (hit_id, image_id, user_id, hit_date, type) VALUES ($1::uuid, $2, $3, NOW(), 'image')", uuid(), id, user.ID)
	http.Redirect(w, r, a.mediaPath(path), http.StatusTemporaryRedirect)
}

func (a *application) favoriteImage(w http.ResponseWriter, r *http.Request, currentUser user) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	command, err := a.pool.Exec(r.Context(), `
INSERT INTO image_favorite (user_id, image_id)
SELECT $1, $2
WHERE EXISTS (SELECT 1 FROM image WHERE id = $2)
ON CONFLICT (user_id, image_id) DO NOTHING`, currentUser.ID, id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Database unavailable")
		return
	}
	if command.RowsAffected() == 0 {
		var exists bool
		if err := a.pool.QueryRow(r.Context(), "SELECT EXISTS (SELECT 1 FROM image WHERE id = $1)", id).Scan(&exists); err != nil || !exists {
			writeError(w, http.StatusNotFound, "Image not found")
			return
		}
	}
	writeJSON(w, http.StatusOK, map[string]bool{"favorite": true})
}

func (a *application) unfavoriteImage(w http.ResponseWriter, r *http.Request, currentUser user) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	command, err := a.pool.Exec(r.Context(), "DELETE FROM image_favorite WHERE user_id = $1 AND image_id = $2", currentUser.ID, id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Database unavailable")
		return
	}
	if command.RowsAffected() == 0 {
		var exists bool
		if err := a.pool.QueryRow(r.Context(), "SELECT EXISTS (SELECT 1 FROM image WHERE id = $1)", id).Scan(&exists); err != nil || !exists {
			writeError(w, http.StatusNotFound, "Image not found")
			return
		}
	}
	writeJSON(w, http.StatusOK, map[string]bool{"favorite": false})
}

func (a *application) contextUpdate(w http.ResponseWriter, r *http.Request, user user) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	var body struct {
		Tags    *[]string `json:"tags"`
		Comment *string   `json:"comment"`
	}
	if !decodeJSONWithLimit(w, r, &body, maxCommentRequestBytes) {
		return
	}
	if body.Tags == nil && body.Comment == nil {
		writeError(w, 422, "Supply tags or comment")
		return
	}
	tx, err := a.pool.Begin(r.Context())
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	defer func() { _ = tx.Rollback(r.Context()) }()
	var exists int32
	if err := tx.QueryRow(r.Context(), "SELECT id FROM image WHERE id = $1", id).Scan(&exists); errors.Is(err, pgx.ErrNoRows) {
		writeError(w, 404, "Image not found")
		return
	} else if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	if body.Tags != nil {
		if !user.Admin {
			writeError(w, 403, "Administrator access required")
			return
		}
		if len(*body.Tags) > 50 {
			writeError(w, 422, "Invalid tag")
			return
		}
		names := map[string]bool{}
		for _, tag := range *body.Tags {
			clean, cleanErr := cleanTag(tag)
			if cleanErr != nil {
				writeError(w, 422, "Invalid tag")
				return
			}
			names[clean] = true
		}
		if _, err := tx.Exec(r.Context(), "DELETE FROM tag_image WHERE image = $1", id); err != nil {
			writeError(w, 500, "Database unavailable")
			return
		}
		for name := range names {
			var tagID int32
			if err := tx.QueryRow(r.Context(), "INSERT INTO tag (name) VALUES ($1) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id", name).Scan(&tagID); err != nil {
				writeError(w, 500, "Database unavailable")
				return
			}
			if _, err := tx.Exec(r.Context(), "INSERT INTO tag_image (image, tag) VALUES ($1, $2)", id, tagID); err != nil {
				writeError(w, 500, "Database unavailable")
				return
			}
		}
	}
	if body.Comment != nil {
		text := strings.TrimSpace(*body.Comment)
		if text == "" || len(text) > maxCommentTextBytes || containsControl(text) {
			writeError(w, 422, "Comment must contain 1–8192 UTF-8 bytes without control characters")
			return
		}
		if _, err := tx.Exec(r.Context(), "INSERT INTO message (from_user, image, text, reply_to, message_date) VALUES ($1, $2, $3, NULL, NOW())", user.ID, id, text); err != nil {
			writeError(w, 500, "Database unavailable")
			return
		}
	}
	if err := tx.Commit(r.Context()); err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	item, err := a.imageByID(r.Context(), id, user.ID)
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	writeJSON(w, 200, item)
}

func (a *application) updateImage(w http.ResponseWriter, r *http.Request, user user) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	var body struct {
		Name string `json:"name"`
	}
	if !decodeJSON(w, r, &body) {
		return
	}
	name := strings.Join(strings.Fields(body.Name), " ")
	if name == "" || len(name) > 200 || containsControl(name) {
		writeError(w, 422, "Invalid title")
		return
	}
	command, err := a.pool.Exec(r.Context(), "UPDATE image SET name = $1 WHERE id = $2", name, id)
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	if command.RowsAffected() == 0 {
		writeError(w, 404, "Image not found")
		return
	}
	_, _ = a.pool.Exec(r.Context(), "INSERT INTO audit_event (actor_id, action, object_type, object_id, created_at) VALUES ($1, 'edit_title', 'image', $2, NOW())", user.ID, strconv.Itoa(int(id)))
	item, err := a.imageByID(r.Context(), id, user.ID)
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	writeJSON(w, 200, item)
}

func (a *application) addComment(w http.ResponseWriter, r *http.Request, user user) {
	id, ok := pathID(w, r)
	if !ok {
		return
	}
	var body struct {
		Text    string `json:"text"`
		ReplyTo *int32 `json:"reply_to"`
	}
	if !decodeJSONWithLimit(w, r, &body, maxCommentRequestBytes) {
		return
	}
	text := strings.TrimSpace(body.Text)
	if text == "" || len(text) > maxCommentTextBytes || containsControl(text) {
		writeError(w, 422, "Comment must contain 1–8192 UTF-8 bytes without control characters")
		return
	}
	if body.ReplyTo != nil {
		var parentImage int32
		var reply *int32
		if err := a.pool.QueryRow(r.Context(), "SELECT image, reply_to FROM message WHERE id = $1", *body.ReplyTo).Scan(&parentImage, &reply); err != nil || parentImage != id {
			writeError(w, 422, "Invalid reply target")
			return
		}
		for depth := 1; reply != nil; depth++ {
			if depth >= 8 {
				writeError(w, 422, "Reply depth exceeded")
				return
			}
			if err := a.pool.QueryRow(r.Context(), "SELECT reply_to FROM message WHERE id = $1 AND image = $2", *reply, id).Scan(&reply); err != nil {
				writeError(w, 422, "Invalid comment thread")
				return
			}
		}
	}
	command, err := a.pool.Exec(r.Context(), "INSERT INTO message (from_user, image, text, reply_to, message_date) SELECT $1, $2, $3, $4, NOW() WHERE EXISTS (SELECT 1 FROM image WHERE id = $2)", user.ID, id, text, body.ReplyTo)
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	if command.RowsAffected() == 0 {
		writeError(w, 404, "Image not found")
		return
	}
	item, err := a.imageByID(r.Context(), id, user.ID)
	if err != nil {
		writeError(w, 500, "Database unavailable")
		return
	}
	writeJSON(w, 200, item)
}

func (a *application) mediaPath(path string) string {
	return strings.TrimRight(a.config.mediaURL, "/") + "/" + encodedPath(path)
}

func encodedPath(path string) string {
	parts := strings.Split(path, "$")
	for i := range parts {
		parts[i] = url.PathEscape(parts[i])
	}
	return strings.Join(parts, "/")
}

func mediaKind(path string) string {
	switch strings.ToLower(filepath.Ext(path)) {
	case ".avi", ".m4v", ".mpe", ".mpeg", ".mpg", ".mov", ".mp4", ".webm", ".wmv":
		return "video"
	default:
		return "image"
	}
}

func supportedMedia(name string) bool {
	switch strings.ToLower(filepath.Ext(name)) {
	case ".avif", ".avi", ".bmp", ".gif", ".jpeg", ".jpg", ".m4v", ".mpe", ".mpeg", ".mpg", ".mov", ".mp4", ".png", ".tif", ".tiff", ".webm", ".webp", ".wmv":
		return true
	default:
		return false
	}
}

func supportedDocument(name string) bool {
	switch strings.ToLower(filepath.Ext(name)) {
	case ".htm", ".html", ".log", ".md", ".text", ".txt":
		return true
	default:
		return false
	}
}

func canonicalPath(value string, allowEmpty bool) (string, error) {
	if value == "" && allowEmpty {
		return "", nil
	}
	parts := strings.Split(value, "$")
	if value == "" {
		return "", errors.New("empty")
	}
	for _, part := range parts {
		if !safeComponent(part) {
			return "", errors.New("invalid")
		}
	}
	return strings.Join(parts, "$"), nil
}

func safeComponent(value string) bool {
	if value == "" || value == "." || value == ".." || strings.ContainsAny(value, "$/\\\x00") {
		return false
	}
	return !containsControl(value)
}

func containsControl(value string) bool {
	for _, char := range value {
		if unicode.IsControl(char) {
			return true
		}
	}
	return false
}

func joinCanonical(base, name string) string {
	if base == "" {
		return name
	}
	return base + "$" + name
}

func (a *application) existingPath(canonical string) (mediaPath, error) {
	root, err := filepath.EvalSymlinks(a.config.mediaRoot)
	if err != nil {
		return mediaPath{}, err
	}
	parts := []string{}
	if canonical != "" {
		parts = strings.Split(canonical, "$")
	}
	target := filepath.Join(append([]string{root}, parts...)...)
	resolved, err := filepath.EvalSymlinks(target)
	if err != nil {
		return mediaPath{}, err
	}
	if resolved != root && !strings.HasPrefix(resolved, root+string(filepath.Separator)) {
		return mediaPath{}, errors.New("outside root")
	}
	info, err := os.Lstat(resolved)
	if err != nil || info.Mode()&os.ModeSymlink != 0 {
		return mediaPath{}, errors.New("unavailable")
	}
	return mediaPath{info: info, path: resolved}, nil
}

type mediaPath struct {
	info fs.FileInfo
	path string
}

func pathID(w http.ResponseWriter, r *http.Request) (int32, bool) {
	id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 32)
	if err != nil || id < 1 {
		writeError(w, 404, "Image not found")
		return 0, false
	}
	return int32(id), true
}

func positiveInt(value string, fallback int) int {
	parsed, err := strconv.Atoi(value)
	if err != nil || parsed < 1 {
		return fallback
	}
	return parsed
}

func int32Pointer(value int32) *int32 {
	return &value
}

func cleanTag(value string) (string, error) {
	value = strings.ToLower(strings.Join(strings.Fields(value), " "))
	if value == "" || len(value) > 100 || strings.ContainsAny(value, "/\\") || containsControl(value) {
		return "", errors.New("invalid")
	}
	return value, nil
}

func decodeJSON(w http.ResponseWriter, r *http.Request, target any) bool {
	return decodeJSONWithLimit(w, r, target, 1024)
}

func decodeJSONWithLimit(w http.ResponseWriter, r *http.Request, target any, limit int64) bool {
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, limit))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		writeError(w, 422, "Invalid request")
		return false
	}
	return true
}
