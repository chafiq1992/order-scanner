# Order Scanner

Minimal reproduction of  your Apps‑Script barcode scanner as a FastAPI + React stack ready for Google Cloud Run.

## Environment Variables

The API uses a handful of environment variables.  When running locally you can
place them in a `.env` file and load it with `docker run --env-file=.env` or a
similar mechanism.  Cloud Run reads these values from the service configuration.

| Variable | Description |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy connection string.  A local run can use SQLite (`sqlite+aiosqlite:///./db.sqlite3`) while production might point to a managed Postgres instance. |
| `SHOPIFY_STORES_JSON` | JSON array describing Shopify stores.  Each entry must contain `name`, `api_key`, `password` and `domain`.  Instead of this variable you may supply pairs of `*_API_KEY`, `*_PASSWORD` and `*_DOMAIN` variables. |
| `GOOGLE_SHEET_ID` | *(optional)* ID of the Google Sheet used for logging scans. |
| `GCP_SA_B64` | *(optional)* Base64‑encoded service account JSON with access to the sheet. |
| `STATIC_FILES_PATH` | *(optional)* Location of the built frontend files. Defaults to `static`. |

Example `.env` snippet:

```dotenv
DATABASE_URL=sqlite+aiosqlite:///./db.sqlite3
GOOGLE_SHEET_ID=1aBcD2EfGhIjKlMnOpQrStUvWxYz
GCP_SA_B64=eyJ0eXAiOiJKV1QiLCJhbGciOiJ...
SHOPIFY_STORES_JSON=[{"name":"main","api_key":"abc","password":"secret","domain":"example.myshopify.com"}]
```

## Building the Frontend

The web UI lives in the `frontend` directory and is built with Vite.  Install
its dependencies and run the build script:

```bash
cd frontend
npm ci
npm run build
```

This produces a `dist/` folder that can be served by the API container.  When
developing locally with `npm run dev` make sure the `VITE_API_BASE_URL`
environment variable points at your API instance so the app can reach the
backend. The build step can also make use of this variable, but if it is not
defined the UI will fall back to using the same origin as the page, which works
for single-container deployments.

## Running the Tests

Install backend dependencies (including the test requirements) and execute `pytest` from the repository root:

```bash
pip install -r backend/requirements.txt
pytest
```

## License

This project is licensed under the [MIT License](LICENSE).
