# backend/Dockerfile
# ---------- build front‑end ----------
FROM node:20-alpine AS client-builder
WORKDIR /web
COPY ../frontend ./frontend
RUN cd frontend && \
    npm ci && \
    npm run build

# ---------- python runtime ----------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# serve static files built above
COPY --from=client-builder /web/frontend/dist ./static
# FastAPI will auto‑mount ./static
ENV STATIC_FILES_PATH=/app/static
CMD ["uvicorn", "app.main:app", "--host","0.0.0.0","--port","8080"]
