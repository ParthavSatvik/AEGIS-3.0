# AEGIS 3.0 — single-service image: FastAPI serves the API and the built React frontend on one origin.
# Simulation only: no connection to real equipment. See docs/DEPLOYMENT.md.

# ---- stage 1: build the frontend
FROM node:20-alpine AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- stage 2: runtime
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AEGIS_ENV=production
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend/aegis backend/aegis
COPY data/real data/real
COPY --from=web /app/frontend/dist frontend/dist
RUN useradd --create-home --uid 10001 aegis && chown -R aegis /app
USER aegis
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/api/health',timeout=4)" || exit 1
# Hosting platforms (e.g. Render) inject $PORT; default 8000 locally.
CMD ["sh", "-c", "exec python -m uvicorn aegis.api:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
