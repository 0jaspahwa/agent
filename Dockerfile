# Two stages. 1: build the React interface (Node). 2: the FastAPI app, which serves the API, the operations
# pages at /ops and the built interface at /. On every start the app creates any missing tables and seeds policy
# v5.0, and the task kit if /app/data holds it (docker-compose.yml mounts ./data there read-only); both are safe
# to repeat. The image never contains kit files (.dockerignore): on a host without the mount, such as Render, a
# Procurement user uploads the kit zip under Load kit data.
FROM node:22-alpine AS interface
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY docs/sample_amendments/ docs/sample_amendments/
COPY docs/policy_schema.md docs/policy_schema.md
COPY --from=interface /frontend/dist frontend/dist

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/health', timeout=4)"

# PORT is set by hosts such as Render; locally it is 8000. Proxy headers: the host's load balancer is trusted.
CMD ["sh", "-c", "uvicorn main:app --app-dir backend --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
