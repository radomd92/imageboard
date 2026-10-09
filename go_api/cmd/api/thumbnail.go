package main

import (
	"bytes"
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	stdimage "image"
	"image/color"
	stddraw "image/draw"
	_ "image/gif"
	"image/jpeg"
	_ "image/png"
	"io"
	"math"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	_ "golang.org/x/image/bmp"
	"golang.org/x/image/draw"
	_ "golang.org/x/image/tiff"
	_ "golang.org/x/image/webp"
)

const (
	thumbnailSmallWidth      = 160
	thumbnailLargeWidth      = 320
	maxThumbnailSourceBytes  = 20 << 20
	maxThumbnailSourcePixels = 20_000_000
)

func (a *application) thumbnail(w http.ResponseWriter, r *http.Request, currentUser user) {
	canonicalPath, variant, err := parseThumbnailPath(r.URL.Path)
	if err != nil {
		writeError(w, http.StatusNotFound, "Thumbnail not found")
		return
	}
	media, err := a.existingPath(canonicalPath)
	if err != nil || !media.info.Mode().IsRegular() || !supportedMedia(canonicalPath) || mediaKind(canonicalPath) != "image" {
		writeError(w, http.StatusNotFound, "Thumbnail not found")
		return
	}
	if !currentUser.Admin {
		var indexed bool
		if err := a.pool.QueryRow(r.Context(), "SELECT EXISTS (SELECT 1 FROM image WHERE image_path = $1)", canonicalPath).Scan(&indexed); err != nil {
			writeError(w, http.StatusInternalServerError, "Database unavailable")
			return
		}
		if !indexed {
			writeError(w, http.StatusForbidden, "Media is not indexed")
			return
		}
	}

	cacheKey := a.thumbnailCacheKey(canonicalPath)
	sourceModified := media.info.ModTime().UTC().Truncate(time.Microsecond)
	thumbnail, found, err := a.loadThumbnail(r.Context(), cacheKey, variant, media.info.Size(), sourceModified)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Thumbnail cache unavailable")
		return
	}
	if !found {
		thumbnail, err = generateThumbnail(media.path, variant, variant)
		if err != nil {
			writeError(w, http.StatusUnsupportedMediaType, "Thumbnail unavailable")
			return
		}
		nonce, ciphertext, err := encryptThumbnail(a.config.thumbnailEncryptionKey, thumbnailAdditionalData(cacheKey, variant), thumbnail)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "Thumbnail cache unavailable")
			return
		}
		if err := a.storeThumbnail(r.Context(), cacheKey, variant, media.info.Size(), sourceModified, nonce, ciphertext); err != nil {
			writeError(w, http.StatusInternalServerError, "Thumbnail cache unavailable")
			return
		}
	}
	w.Header().Set("Content-Type", "image/jpeg")
	w.Header().Set("Content-Length", strconv.Itoa(len(thumbnail)))
	_, _ = w.Write(thumbnail)
}

func parseThumbnailPath(requestPath string) (string, int, error) {
	const prefix = "/thumbnail/"
	if !strings.HasPrefix(requestPath, prefix) {
		return "", 0, errors.New("invalid path")
	}
	parts := strings.Split(strings.TrimPrefix(requestPath, prefix), "/")
	if len(parts) < 2 {
		return "", 0, errors.New("invalid path")
	}
	variant := 0
	switch parts[len(parts)-1] {
	case "small":
		variant = thumbnailSmallWidth
	case "large":
		variant = thumbnailLargeWidth
	default:
		return "", 0, errors.New("invalid variant")
	}
	canonicalPath, err := canonicalPath(strings.Join(parts[:len(parts)-1], "$"), false)
	return canonicalPath, variant, err
}

func (a *application) thumbnailCacheKey(canonicalPath string) []byte {
	mac := hmac.New(sha256.New, a.config.thumbnailCacheKey[:])
	_, _ = mac.Write([]byte(canonicalPath))
	return mac.Sum(nil)
}

func (a *application) loadThumbnail(ctx context.Context, cacheKey []byte, variant int, sourceSize int64, sourceModified time.Time) ([]byte, bool, error) {
	var cachedSize int64
	var cachedModified time.Time
	var nonce, ciphertext []byte
	err := a.pool.QueryRow(ctx, `SELECT source_size, source_modified_at, nonce, ciphertext
FROM thumbnail_cache WHERE cache_key = $1 AND variant = $2`, cacheKey, variant).Scan(&cachedSize, &cachedModified, &nonce, &ciphertext)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	if cachedSize != sourceSize || !cachedModified.Equal(sourceModified) {
		return nil, false, nil
	}
	thumbnail, err := decryptThumbnail(a.config.thumbnailEncryptionKey, thumbnailAdditionalData(cacheKey, variant), nonce, ciphertext)
	if err == nil {
		return thumbnail, true, nil
	}
	if _, deleteErr := a.pool.Exec(ctx, "DELETE FROM thumbnail_cache WHERE cache_key = $1 AND variant = $2", cacheKey, variant); deleteErr != nil {
		return nil, false, deleteErr
	}
	return nil, false, nil
}

func (a *application) storeThumbnail(ctx context.Context, cacheKey []byte, variant int, sourceSize int64, sourceModified time.Time, nonce, ciphertext []byte) error {
	_, err := a.pool.Exec(ctx, `INSERT INTO thumbnail_cache
(cache_key, variant, source_size, source_modified_at, nonce, ciphertext, content_type)
VALUES ($1, $2, $3, $4, $5, $6, 'image/jpeg')
ON CONFLICT (cache_key, variant) DO UPDATE SET
source_size = EXCLUDED.source_size,
source_modified_at = EXCLUDED.source_modified_at,
nonce = EXCLUDED.nonce,
ciphertext = EXCLUDED.ciphertext,
content_type = EXCLUDED.content_type,
created_at = NOW()`, cacheKey, variant, sourceSize, sourceModified, nonce, ciphertext)
	return err
}

func thumbnailAdditionalData(cacheKey []byte, variant int) []byte {
	additionalData := make([]byte, len(cacheKey)+2)
	copy(additionalData, cacheKey)
	binary.BigEndian.PutUint16(additionalData[len(cacheKey):], uint16(variant))
	return additionalData
}

func encryptThumbnail(key [32]byte, additionalData, plaintext []byte) ([]byte, []byte, error) {
	block, err := aes.NewCipher(key[:])
	if err != nil {
		return nil, nil, err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, nil, err
	}
	nonce := make([]byte, gcm.NonceSize())
	if _, err := rand.Read(nonce); err != nil {
		return nil, nil, err
	}
	return nonce, gcm.Seal(nil, nonce, plaintext, additionalData), nil
}

func decryptThumbnail(key [32]byte, additionalData, nonce, ciphertext []byte) ([]byte, error) {
	block, err := aes.NewCipher(key[:])
	if err != nil {
		return nil, err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	if len(nonce) != gcm.NonceSize() {
		return nil, errors.New("invalid nonce")
	}
	return gcm.Open(nil, nonce, ciphertext, additionalData)
}

func generateThumbnail(path string, maxWidth, maxHeight int) ([]byte, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer func() { _ = file.Close() }()
	source, err := io.ReadAll(io.LimitReader(file, maxThumbnailSourceBytes+1))
	if err != nil || len(source) > maxThumbnailSourceBytes {
		return nil, errors.New("source too large")
	}
	config, _, err := stdimage.DecodeConfig(bytes.NewReader(source))
	if err != nil || config.Width < 1 || config.Height < 1 || int64(config.Width)*int64(config.Height) > maxThumbnailSourcePixels {
		return nil, errors.New("unsupported source")
	}
	sourceImage, _, err := stdimage.Decode(bytes.NewReader(source))
	if err != nil {
		return nil, err
	}
	width, height := thumbnailDimensions(sourceImage.Bounds().Dx(), sourceImage.Bounds().Dy(), maxWidth, maxHeight)
	destination := stdimage.NewRGBA(stdimage.Rect(0, 0, width, height))
	stddraw.Draw(destination, destination.Bounds(), &stdimage.Uniform{C: color.White}, stdimage.Point{}, stddraw.Src)
	draw.CatmullRom.Scale(destination, destination.Bounds(), sourceImage, sourceImage.Bounds(), draw.Over, nil)
	var encoded bytes.Buffer
	if err := jpeg.Encode(&encoded, destination, &jpeg.Options{Quality: 85}); err != nil {
		return nil, err
	}
	return encoded.Bytes(), nil
}

func thumbnailDimensions(sourceWidth, sourceHeight, maxWidth, maxHeight int) (int, int) {
	if sourceWidth <= maxWidth && sourceHeight <= maxHeight {
		return sourceWidth, sourceHeight
	}
	scale := math.Min(float64(maxWidth)/float64(sourceWidth), float64(maxHeight)/float64(sourceHeight))
	return max(1, int(math.Round(float64(sourceWidth)*scale))), max(1, int(math.Round(float64(sourceHeight)*scale)))
}
