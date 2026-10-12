FROM golang:1.24-bookworm AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN go mod tidy
RUN go test ./...
RUN CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /index-worker ./cmd/index-worker

FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 imageboard \
    && useradd --system --uid 10001 --gid imageboard imageboard
COPY --from=build /index-worker /index-worker
USER 10001:10001
ENTRYPOINT ["/index-worker"]
