FROM ghcr.io/hybridgroup/opencv:4.8.1 AS builder

WORKDIR /app

# Copy modules
COPY go.mod go.sum ./
RUN go mod download

# Copy source
COPY . .

# Ensure deps are tidy (resolves missing go.sum entries)
RUN go mod tidy

# Build
RUN go build -o ingest_server cmd/server/main.go

# Runtime Stage
FROM ghcr.io/hybridgroup/opencv:4.8.1

# Install curl and yt-dlp (standalone binary)
RUN apt-get update && apt-get install -y curl && \
    curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux -o /usr/local/bin/yt-dlp && \
    chmod a+rx /usr/local/bin/yt-dlp

WORKDIR /app
COPY --from=builder /app/ingest_server .

# Default Env Vars
ENV NATS_URL="nats://localhost:4222"

CMD ["./ingest_server"]
