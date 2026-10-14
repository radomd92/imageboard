package embedding

import (
	"fmt"
	"math"
	"strings"
	"testing"
)

func cosine(left, right map[string]float64) float64 {
	var score float64
	for term, weight := range left {
		score += weight * right[term]
	}
	return score
}

func TestVectorsRankSharedContextAndNormalize(t *testing.T) {
	encoder := Vectorizer{TagWeight: 2}
	seed := encoder.Vectorize(Source{Tags: []string{"red_cat"}, Comments: []string{"A red cat sitting beside a window"}})
	related := encoder.Vectorize(Source{Tags: []string{"red cat"}, Comments: []string{"Red cat by the window"}})
	unrelated := encoder.Vectorize(Source{Tags: []string{"aircraft"}, Comments: []string{"Jet aircraft flying over mountains"}})
	if math.Abs(cosine(seed, seed)-1) > 1e-10 {
		t.Fatal("vector is not normalized")
	}
	if cosine(seed, related) <= cosine(seed, unrelated) || cosine(seed, unrelated) != 0 {
		t.Fatal("related context was not ranked above unrelated content")
	}
	if len(encoder.Vectorize(Source{Comments: []string{"the image shows a photo"}})) != 0 {
		t.Fatal("boilerplate should not produce recommendations")
	}
	if seed["t:red cat"] == 0 || seed["w:cat"] == 0 {
		t.Fatal("tag normalization or phrase features missing")
	}
}

func TestVectorsRemainBoundedAndDeterministic(t *testing.T) {
	words := []string{}
	for i := 0; i < 1000; i++ {
		words = append(words, fmt.Sprintf("word%d", i))
	}
	encoder := Vectorizer{TagWeight: 2}
	source := Source{Comments: []string{strings.Join(words, " ")}}
	first, second := encoder.Vectorize(source), encoder.Vectorize(source)
	if len(first) != maxTerms || len(second) != maxTerms {
		t.Fatal("long comments must yield bounded vectors")
	}
	for term, weight := range first {
		if second[term] != weight {
			t.Fatal("tie handling is nondeterministic")
		}
	}
	if encoder.Version() == (Vectorizer{TagWeight: 3}).Version() {
		t.Fatal("weight changes must invalidate stored vectors")
	}
	if SourceHash(source, encoder.Version()) == SourceHash(Source{}, encoder.Version()) {
		t.Fatal("source changes must alter content hash")
	}
	unicode := encoder.Vectorize(Source{Tags: []string{"forêt"}, Comments: []string{"Forêt montagne"}})
	if unicode["w:forêt"] == 0 {
		t.Fatal("Unicode words were lost")
	}
}
