# syntax=docker/dockerfile:1
FROM golang:1.26.10-bookworm@sha256:5de7c99eb78ca5e515a4c340235d0955ec5964a5071c492c15503d7c267da473 AS deps
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download

FROM deps AS verify
COPY . .
RUN --network=none mkdir -p /out/receipts && \
    PREFLIGHT_FIXTURES=/out/receipts go test -race -count=1 -timeout=120s \
      ./sdk/preflightreceipt ./sdk/cliproxy/auth ./internal/api ./internal/pluginhost \
      -run 'TestPreflightReceipt' -v > /out/go-test.txt 2>&1 || (cat /out/go-test.txt; exit 1)
RUN --network=none CGO_ENABLED=1 GOOS=linux go build -buildvcs=false \
    -ldflags="-s -w -X main.Version=8.0.63-preflight-v1 -X main.Commit=6db7d4b8+preflight-v1 -X main.BuildDate=2026-11-13T00:00:00Z" \
    -o /out/cli-proxy-api ./cmd/server/ && /out/cli-proxy-api --help > /out/version.txt 2>&1

# Match Blackhole's runtime base, without touching its checkout or service.
FROM debian:bookworm-slim AS runtime-check
COPY --from=verify /out/cli-proxy-api /usr/local/bin/cli-proxy-api
USER 1000:1000
RUN --network=none /usr/local/bin/cli-proxy-api --help > /tmp/runtime.txt 2>&1

FROM scratch AS artifacts
COPY --from=verify /out/ /
COPY --from=runtime-check /tmp/runtime.txt /runtime.txt
