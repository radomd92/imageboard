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
	"image"
	_ "image/jpeg"
	"os/exec"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

const (
	thumbnailSmallWidth = 160
	maxThumbnailBytes   = 2 << 20
)

func (w *worker) ensureVideoThumbnail(ctx context.Context, file mediaFile) error {
	cacheKey := w.thumbnailKey(file.path)
	var cachedSize int64
	var cachedModified time.Time
	err := w.pool.QueryRow(ctx, "SELECT source_size, source_modified_at FROM thumbnail_cache WHERE cache_key = $1 AND variant = $2", cacheKey, thumbnailSmallWidth).Scan(&cachedSize, &cachedModified)
	if err == nil && cachedSize == file.size && cachedModified.Equal(file.modified) {
		return nil
	}
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return err
	}
	thumbnail, err := generateVideoThumbnail(ctx, file.diskPath, thumbnailSmallWidth)
	if err != nil {
		return err
	}
	nonce, ciphertext, err := encryptThumbnail(w.thumbnailEncryptionKey, thumbnailAdditionalData(cacheKey, thumbnailSmallWidth), thumbnail)
	if err != nil {
		return err
	}
	_, err = w.pool.Exec(ctx, `INSERT INTO thumbnail_cache
(cache_key, variant, source_size, source_modified_at, nonce, ciphertext, content_type)
VALUES ($1, $2, $3, $4, $5, $6, 'image/jpeg')
ON CONFLICT (cache_key, variant) DO UPDATE SET
source_size = EXCLUDED.source_size, source_modified_at = EXCLUDED.source_modified_at,
nonce = EXCLUDED.nonce, ciphertext = EXCLUDED.ciphertext, content_type = EXCLUDED.content_type,
created_at = NOW()`, cacheKey, thumbnailSmallWidth, file.size, file.modified, nonce, ciphertext)
	return err
}

func generateVideoThumbnail(parent context.Context, path string, size int) ([]byte, error) {
	ctx, cancel := context.WithTimeout(parent, 30*time.Second)
	defer cancel()
	durationOutput, err := exec.CommandContext(ctx, "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path).Output()
	if err != nil {
		return nil, errors.New("unable to read video duration")
	}
	duration, err := strconv.ParseFloat(strings.TrimSpace(string(durationOutput)), 64)
	if err != nil || duration <= 0 {
		return nil, errors.New("invalid video duration")
	}
	times := videoFrameTimes(duration)
	tile := max(1, size/2)
	args := []string{"-v", "error"}
	for _, timestamp := range times {
		args = append(args, "-ss", strconv.FormatFloat(timestamp, 'f', 3, 64), "-i", path)
	}
	filter := contactSheetFilter(tile)
	args = append(args, "-filter_complex", filter, "-map", "[out]", "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1")
	output, err := exec.CommandContext(ctx, "ffmpeg", args...).Output()
	if err != nil || len(output) == 0 || len(output) > maxThumbnailBytes {
		return nil, errors.New("unable to extract video frames")
	}
	config, _, err := image.DecodeConfig(bytes.NewReader(output))
	if err != nil || config.Width != size || config.Height != size {
		return nil, errors.New("invalid video thumbnail")
	}
	return output, nil
}

func videoFrameTimes(duration float64) [4]float64 {
	end := max(0, duration-0.1)
	times := [4]float64{5, 30, 45, 60}
	for i := range times {
		if times[i] > end {
			times[i] = end
		}
	}
	return times
}

func contactSheetFilter(tile int) string {
	scale := "scale=" + strconv.Itoa(tile) + ":" + strconv.Itoa(tile) + ":force_original_aspect_ratio=decrease,pad=" + strconv.Itoa(tile) + ":" + strconv.Itoa(tile) + ":(ow-iw)/2:(oh-ih)/2"
	return "[0:v]" + scale + "[a];[1:v]" + scale + "[b];[2:v]" + scale + "[c];[3:v]" + scale + "[d];[a][b]hstack[top];[c][d]hstack[bottom];[top][bottom]vstack[out]"
}

func (w *worker) thumbnailKey(path string) []byte {
	mac := hmac.New(sha256.New, w.thumbnailCacheKey[:])
	_, _ = mac.Write([]byte(path))
	return mac.Sum(nil)
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
