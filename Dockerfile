FROM python:3.11-slim

LABEL org.opencontainers.image.title="OpenSRM" \
      org.opencontainers.image.description="Self-hosted attendance dashboard for the SRM Student Portal" \
      org.opencontainers.image.url="https://github.com/thenabbu/OpenSRM" \
      org.opencontainers.image.source="https://github.com/thenabbu/OpenSRM" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="thenabbu"

# System deps + chromium directly (playwright --with-deps fails on trixie)
# Phase 2: strip system cruft not needed for headless chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libatspi2.0-0 libx11-xcb1 fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/share/icons /usr/share/doc /usr/share/mime \
             /usr/share/X11 /usr/lib/systemd /usr/share/gtk-3.0 \
             /usr/bin/perl /usr/share/zsh

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium
ENV PATH="/app/.venv/bin:/usr/local/bin:/usr/bin:/bin"

# Install deps from lockfile (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project \
    # Phase 1: eliminate uv cache (~540 MB)
    && rm -rf /root/.cache \
    # Phase 1: remove unused ddddocr models (~33 MB) — only beta model used
    && rm -f /app/.venv/lib/python3.11/site-packages/ddddocr/common_det.onnx \
             /app/.venv/lib/python3.11/site-packages/ddddocr/common_old.onnx

# Copy app code
COPY . .

EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "-w", "1", "--threads", "8", "-t", "120", "--worker-class", "gthread", "-b", "0.0.0.0:8080", "app.app:app"]
