FROM golang:1.24-bookworm AS build
WORKDIR /src
COPY go_api/go.mod go_api/go.sum ./
RUN go mod download
COPY go_api .
RUN go test ./...
RUN CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /embedding-worker ./cmd/embedding-worker

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /embedding-worker /embedding-worker
USER 10001:10001
ENTRYPOINT ["/embedding-worker"]
