FROM python:3.13-slim AS base

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

# ── API target ───────────────────────────────────────────────────────
FROM base AS api
RUN pip install --no-cache-dir ".[api]"
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1
CMD ["uvicorn", "alethic_kernel.api.app:create_app", "--factory", "--host", "0.0.0.0"]

# ── Benchmark target ─────────────────────────────────────────────────
FROM base AS bench
CMD ["python", "-m", "alethic_kernel.run", "--no-llm"]
