# syntax=docker/dockerfile:1

# ---- builder: build a wheel with hatchling ----
FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m build --wheel

# ---- runtime: install the wheel, run as non-root ----
FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 10001 appuser
WORKDIR /app
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl
USER appuser

# Config is mounted at runtime; secrets come from env (HCM_* vars).
ENV CONFIG_FILE=/app/config.toml
# For HTTP transport (transport.type = "http"); ignored for stdio.
EXPOSE 8000

ENTRYPOINT ["aj-fusion-hcm-mcp"]
