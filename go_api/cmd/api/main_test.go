package main

import (
	"bytes"
	stdimage "image"
	"image/color"
	"image/jpeg"
	"os"
	"strings"
	"testing"
)

func TestVerifyWerkzeugScryptPassword(t *testing.T) {
	app := application{scryptSem: make(chan struct{}, 1)}
	hash := "scrypt:32768:8:1$uIGJ6F5eMmcuu1zl$bff30f30bcd2cee9043a8c8bd7c16305122b2dd47ab71504b680ffa4ca2da3a33bd1c490fa956bae305d6cc42e7054b64808fc10f1bb2e5e2ea1d332fc6c6b45"

	if !app.verifyPassword(hash, "go-api-test-password") {
		t.Fatal("Werkzeug scrypt password was rejected")
	}
	if app.verifyPassword(hash, "incorrect password") {
		t.Fatal("incorrect password was accepted")
	}
}

func TestCanonicalPathRejectsUnsafeComponents(t *testing.T) {
	valid, err := canonicalPath("album$photo.jpg", false)
	if err != nil || valid != "album$photo.jpg" {
		t.Fatalf("valid path rejected: %q, %v", valid, err)
	}

	for _, path := range []string{"", ".", "..", "album$..", "album/file", "album\\file", "album\x00file"} {
		if _, err := canonicalPath(path, false); err == nil {
			t.Fatalf("unsafe path accepted: %q", path)
		}
	}
}

func TestUUIDProducesRFC4122V4Shape(t *testing.T) {
	value := uuid()
	if len(value) != 36 || value[14] != '4' || value[8] != '-' || value[13] != '-' || value[18] != '-' || value[23] != '-' {
		t.Fatalf("invalid UUID: %q", value)
	}
}

func TestMPEGExtensionsAreVideos(t *testing.T) {
	for _, name := range []string{"movie.mpg", "movie.mpeg", "movie.mpe"} {
		if !supportedMedia(name) || mediaKind(name) != "video" {
			t.Fatalf("MPEG video extension rejected: %q", name)
		}
	}
}

func TestThumbnailEncryptionBindsCacheKeyAndVariant(t *testing.T) {
	key := derivedKey("test secret", "thumbnail encryption v1")
	cacheKey := []byte("cache-key")
	plaintext := []byte("thumbnail bytes")
	nonce, ciphertext, err := encryptThumbnail(key, thumbnailAdditionalData(cacheKey, thumbnailSmallWidth), plaintext)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Equal(ciphertext, plaintext) {
		t.Fatal("thumbnail stored as plaintext")
	}
	decrypted, err := decryptThumbnail(key, thumbnailAdditionalData(cacheKey, thumbnailSmallWidth), nonce, ciphertext)
	if err != nil || !bytes.Equal(decrypted, plaintext) {
		t.Fatalf("thumbnail did not round-trip: %v", err)
	}
	if _, err := decryptThumbnail(key, thumbnailAdditionalData(cacheKey, thumbnailLargeWidth), nonce, ciphertext); err == nil {
		t.Fatal("thumbnail decrypted with a different variant")
	}
}

func TestGenerateThumbnail(t *testing.T) {
	path := t.TempDir() + "/source.jpg"
	file, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	source := stdimage.NewRGBA(stdimage.Rect(0, 0, 400, 200))
	for x := 0; x < 400; x++ {
		for y := 0; y < 200; y++ {
			source.Set(x, y, color.RGBA{R: 60, G: 120, B: 180, A: 255})
		}
	}
	if err := jpeg.Encode(file, source, nil); err != nil {
		_ = file.Close()
		t.Fatal(err)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	thumbnail, err := generateThumbnail(path, thumbnailSmallWidth, thumbnailSmallWidth)
	if err != nil {
		t.Fatal(err)
	}
	config, _, err := stdimage.DecodeConfig(bytes.NewReader(thumbnail))
	if err != nil || config.Width != 160 || config.Height != 80 {
		t.Fatalf("unexpected thumbnail dimensions: %dx%d, %v", config.Width, config.Height, err)
	}
}

func TestParseThumbnailPath(t *testing.T) {
	path, variant, err := parseThumbnailPath("/thumbnail/album/photo.jpg/small")
	if err != nil || path != "album$photo.jpg" || variant != thumbnailSmallWidth {
		t.Fatalf("valid thumbnail path rejected: %q, %d, %v", path, variant, err)
	}
	if _, _, err := parseThumbnailPath("/thumbnail/album/../photo.jpg/small"); err == nil {
		t.Fatal("unsafe thumbnail path accepted")
	}
}

func TestParseImageSearch(t *testing.T) {
	search, err := parseImageSearch("#tag1 #tag2 [comment 1] [comment 2] 'path term1' 'path term2'")
	if err != nil {
		t.Fatal(err)
	}
	sql, values := compileTestSearch(search.root)
	if countSearchNodes(search.root, imageSearchAnd) != 5 {
		t.Fatalf("expected implicit AND terms: %s", sql)
	}
	expected := []string{"tag1", "tag2", "comment 1", "comment 2", "path term1", "path term2"}
	if strings.Join(values, ",") != strings.Join(expected, ",") {
		t.Fatalf("unexpected search values: %#v", values)
	}
	if _, err := parseImageSearch("[unfinished"); err == nil {
		t.Fatal("unterminated comment accepted")
	}
	search, err = parseImageSearch("#tag_with_space ![comment_with_space] !'path_with_space'")
	if err != nil {
		t.Fatal(err)
	}
	_, values = compileTestSearch(search.root)
	expected = []string{"tag with space", "comment with space", "path with space"}
	if strings.Join(values, ",") != strings.Join(expected, ",") {
		t.Fatalf("underscores were not normalized: %#v", values)
	}
}

func TestParseImageSearchOperators(t *testing.T) {
	search, err := parseImageSearch("(#cat | #dog) + !#kitten + ![draft] + !'archive'")
	if err != nil {
		t.Fatal(err)
	}
	sql, values := compileTestSearch(search.root)
	if !strings.Contains(sql, " OR ") || strings.Count(sql, "NOT (") != 3 {
		t.Fatalf("operators were not compiled: %s", sql)
	}
	expected := []string{"cat", "dog", "kitten", "draft", "archive"}
	if strings.Join(values, ",") != strings.Join(expected, ",") {
		t.Fatalf("unexpected operator values: %#v", values)
	}

	search, err = parseImageSearch("#cat | #dog + !#kitten")
	if err != nil {
		t.Fatal(err)
	}
	if search.root.kind != imageSearchOr || search.root.right.kind != imageSearchAnd {
		t.Fatalf("incorrect operator precedence: %#v", search.root)
	}

	for _, query := range []string{"!plain", "!", "#cat |", "(#cat", "#cat + )"} {
		if _, err := parseImageSearch(query); err == nil {
			t.Fatalf("invalid query accepted: %q", query)
		}
	}
}

func compileTestSearch(node *imageSearchNode) (string, []string) {
	values := []string{}
	sql := compileImageSearch(node, func(value any) string {
		values = append(values, value.(string))
		return "$" + string(rune('1'+len(values)-1))
	})
	return sql, values
}

func countSearchNodes(node *imageSearchNode, kind imageSearchNodeKind) int {
	if node == nil {
		return 0
	}
	count := 0
	if node.kind == kind {
		count = 1
	}
	return count + countSearchNodes(node.left, kind) + countSearchNodes(node.right, kind)
}
