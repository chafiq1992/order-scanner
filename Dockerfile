# Dockerfile at repo‑root  (✅ copy‑paste this)

# ---------- build React front‑end ----------
FROM node:20-alpine AS client-builder
WORKDIR /web
COPY frontend ./frontend          # <── change here
RUN cd frontend && npm ci && npm run build

# ---------- Python + FastAPI ----------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY backend/requirements.txt .    # path is now within context
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=client-builder /web/frontend/dist ./static
ENV STATIC_FILES_PATH=/app/static
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
