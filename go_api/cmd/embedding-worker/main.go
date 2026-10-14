package main

import (
	"context"
	"log"
	"math"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"imageboard/api/internal/embedding"

	"github.com/jackc/pgx/v5/pgxpool"
)

func main() {
	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()
	url := strings.Replace(os.Getenv("IMAGEBOARD_DATABASE_URL"), "postgresql+psycopg://", "postgres://", 1)
	pool, err := pgxpool.New(ctx, url)
	if err != nil {
		log.Fatal("embedding database configuration failed")
	}
	defer pool.Close()
	weight := 2.0
	if value := os.Getenv("EMBEDDING_TAG_WEIGHT"); value != "" {
		weight, err = strconv.ParseFloat(value, 64)
		if err != nil || weight <= 0 || weight > 10 || math.IsNaN(weight) || math.IsInf(weight, 0) {
			log.Fatal("invalid embedding tag weight")
		}
	}
	worker := embedding.Worker{Pool: pool, Encoder: embedding.Vectorizer{TagWeight: weight}}
	for ctx.Err() == nil {
		if err := worker.Configure(ctx); err == nil {
			log.Print("lexical vector indexing configured; durable backfill starting")
			worker.Run(ctx)
			return
		}
		log.Print("waiting for vector database schema")
		select {
		case <-ctx.Done():
		case <-time.After(15 * time.Second):
		}
	}
}
