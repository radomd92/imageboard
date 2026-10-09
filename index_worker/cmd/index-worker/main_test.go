package main

import "testing"

func TestSafePartsRejectsTraversalAndConfidentialityHazards(t *testing.T) {
	for _, parts := range [][]string{{"album", "photo.jpg"}, {"."}, {".."}, {"album$private"}, {"album/file"}, {"album\\file"}, {"album\x00file"}} {
		want := len(parts) == 2
		if got := safeParts(parts); got != want {
			t.Fatalf("safeParts(%q) = %v, want %v", parts, got, want)
		}
	}
}

func TestSupportedMedia(t *testing.T) {
	if !supportedMedia("example.JPEG") || !supportedMedia("movie.webm") || !supportedMedia("movie.mpg") {
		t.Fatal("supported extensions rejected")
	}
	if supportedMedia("notes.txt") || supportedMedia("no-extension") {
		t.Fatal("unsupported extension accepted")
	}
}

func TestStaleDeletionStaysInsideRequestedScope(t *testing.T) {
	query, args := staleDeleteQuery(job{id: "job-id", rootPath: "album$subdir"}, true)
	if query != "DELETE FROM image WHERE last_index_job IS DISTINCT FROM $2 AND (image_path = $1 OR image_path LIKE $1 || '$%')" {
		t.Fatalf("unexpected query: %s", query)
	}
	if len(args) != 2 || args[0] != "album$subdir" || args[1] != "job-id" {
		t.Fatalf("unexpected query arguments: %v", args)
	}
}
