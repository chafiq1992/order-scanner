FROM node:20-alpine
WORKDIR /app
COPY . .
RUN npm ci && npm run build
# This container only serves the built files (e.g. with nginx) or
# upload `dist/` to Cloud Storage for zero‑cost hosting.
