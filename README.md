# Order Scanner

Minimal reproduction of your Apps‑Script barcode scanner as a FastAPI + React stack ready for Google Cloud Run.

## Environment variables

The API relies on several environment variables:

- `DATABASE_URL` – PostgreSQL connection string used by SQLAlchemy.
- `SHOPIFY_STORES_JSON` – JSON array describing each Shopify store (or set `<STORE>_API_KEY`, `<STORE>_PASSWORD` and `<STORE>_DOMAIN` per store).
- `GOOGLE_SHEET_ID` – ID of the Google Sheet to append scan results to.
- `GCP_SA_B64` – base64 encoded service account JSON for Google Sheets access.
- `STATIC_FILES_PATH` – optional path for static files (defaults to `static`).

These must be present when deploying via the GitHub workflow.

## Local development

1. Install Python requirements:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```
2. Start the React dev server in another terminal:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
3. Run the FastAPI app:
   ```bash
   uvicorn app.main:app --reload
   ```
   Ensure all required environment variables are exported before starting.

## Docker

Build and run the full stack using Docker:

```bash
docker build -t order-scanner .
docker run -p 8080:8080 \
  -e DATABASE_URL=... \
  -e SHOPIFY_STORES_JSON=... \
  -e GOOGLE_SHEET_ID=... \
  -e GCP_SA_B64=... \
  order-scanner
```

The container serves the React frontend at `/` and the API endpoints such as `/scan` on port `8080`.
