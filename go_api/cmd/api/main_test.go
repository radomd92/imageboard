package main

import "testing"

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
