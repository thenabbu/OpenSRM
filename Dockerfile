FROM python:3.11-slim AS builder

# Runtime deps only (no chromium binary — Playwright manages headless shell)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libatspi2.0-0 libx11-xcb1 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Install uv and Python packages
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project \
    && rm -f /app/.venv/lib/python3.11/site-packages/ddddocr/common_det.onnx \
             /app/.venv/lib/python3.11/site-packages/ddddocr/common_old.onnx

# Install Playwright headless shell only (261MB vs apt chromium 375MB)
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PATH="/app/.venv/bin:$PATH"
RUN playwright install --only-shell chromium

# ── Stage 2: Runtime ──────────────────────────────────────────────
FROM python:3.11-slim

LABEL org.opencontainers.image.title="OpenSRM" \
      org.opencontainers.image.description="Self-hosted attendance dashboard for the SRM Student Portal" \
      org.opencontainers.image.url="https://github.com/thenabbu/OpenSRM" \
      org.opencontainers.image.source="https://github.com/thenabbu/OpenSRM" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="thenabbu"

# Runtime deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libatspi2.0-0 libx11-xcb1 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Copy Python venv from builder
COPY --from=builder /app/.venv /app/.venv
# Copy Playwright headless shell from builder
COPY --from=builder /ms-playwright /ms-playwright

# Find and symlink the headless shell binary
RUN ln -sf $(find /ms-playwright -name chrome-headless-shell -type f | head -1) /usr/local/bin/chromium

ENV CHROMIUM_PATH=/usr/local/bin/chromium
ENV PATH="/app/.venv/bin:/usr/local/bin:/usr/bin:/bin"
WORKDIR /app

# Copy app code
COPY . .

EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "-w", "1", "--threads", "8", "-t", "120", "--worker-class", "gthread", "-b", "0.0.0.0:8080", "app.app:app"]
