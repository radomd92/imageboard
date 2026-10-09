FROM golang:1.24-bookworm AS build

WORKDIR /src
COPY go_api/go.mod go_api/go.sum ./
RUN go mod download
COPY go_api .
RUN go test ./...
RUN CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /imageboard-api ./cmd/api

FROM gcr.io/distroless/static-debian12:nonroot

COPY --from=build /imageboard-api /imageboard-api
COPY imageboard/imageboard/static /static
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["/imageboard-api"]
