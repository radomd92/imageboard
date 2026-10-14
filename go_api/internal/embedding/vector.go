package embedding

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"math"
	"sort"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

const maxTerms = 128
const algorithmVersion = "lexical-v1-logtf-stopwords-tags-128"

type Source struct {
	Tags     []string `json:"tags"`
	Comments []string `json:"comments"`
}

type Vectorizer struct {
	TagWeight float64
}

var stopWords = func() map[string]bool {
	words := `a an and are as at be been being by can could did do does for from had has have he her here hers him his i if in into is it its me more most my no not of on or our ours she so some than that the their theirs them then there these they this those to too up us was we were what when where which who will with would you your yours
image images photo photos photograph photographs picture pictures depicts depicting shows showing visible featuring contains scene view
le la les un une des du de et est en dans au aux avec sur pour par ce cette ces il elle ils elles`
	result := map[string]bool{}
	for _, word := range strings.Fields(words) {
		result[word] = true
	}
	return result
}()

func (v Vectorizer) Version() string {
	sum := sha256.Sum256([]byte(algorithmVersion + ":" + strconv.FormatFloat(v.TagWeight, 'g', -1, 64)))
	return hex.EncodeToString(sum[:])
}

func SourceHash(source Source, version string) string {
	encoded, _ := json.Marshal(struct {
		Source  Source `json:"source"`
		Version string `json:"version"`
	}{source, version})
	sum := sha256.Sum256(encoded)
	return hex.EncodeToString(sum[:])
}

func words(text string) []string {
	return strings.FieldsFunc(strings.ToLower(text), func(r rune) bool { return !unicode.IsLetter(r) && !unicode.IsDigit(r) })
}

// Sparse normalized log-frequency vectors. Tags carry extra weight and an
// exact-phrase feature; bounded dimensions keep indexing and retrieval cheap.
func (v Vectorizer) Vectorize(source Source) map[string]float64 {
	frequencies := map[string]float64{}
	addWords := func(text string, weight float64) {
		for _, word := range words(text) {
			if utf8.RuneCountInString(word) >= 2 && len(word) <= 128 && !stopWords[word] {
				frequencies["w:"+word] += weight
			}
		}
	}
	for _, tag := range source.Tags {
		addWords(tag, v.TagWeight)
		phrase := strings.Join(words(tag), " ")
		if phrase != "" && len(phrase) <= 128 {
			frequencies["t:"+phrase] += v.TagWeight
		}
	}
	for _, comment := range source.Comments {
		addWords(comment, 1)
	}
	terms := make([]string, 0, len(frequencies))
	for term, frequency := range frequencies {
		frequencies[term] = math.Log1p(frequency)
		terms = append(terms, term)
	}
	sort.Slice(terms, func(i, j int) bool {
		if frequencies[terms[i]] == frequencies[terms[j]] {
			return terms[i] < terms[j]
		}
		return frequencies[terms[i]] > frequencies[terms[j]]
	})
	if len(terms) > maxTerms {
		terms = terms[:maxTerms]
	}
	var norm float64
	for _, term := range terms {
		norm += frequencies[term] * frequencies[term]
	}
	result := map[string]float64{}
	if norm == 0 {
		return result
	}
	norm = math.Sqrt(norm)
	for _, term := range terms {
		result[term] = frequencies[term] / norm
	}
	return result
}
