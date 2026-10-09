FROM golang:1.24-bookworm AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN go mod tidy
RUN go test ./...
RUN CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /index-worker ./cmd/index-worker

FROM gcr.io/distroless/static-debian12:nonroot

COPY --from=build /index-worker /index-worker
USER 10001:10001
ENTRYPOINT ["/index-worker"]
