# homeplate

A small self-hosted FastAPI companion app to the [Mealie](https://mealie.io) recipe manager.

## Run locally

    docker compose up

homeplate is on http://localhost:8000 (`/healthz`), Mealie on http://localhost:9925.

## Configuration

| Variable | Meaning |
| --- | --- |
| `MEALIE_URL` | Where homeplate reaches Mealie (default `http://mealie:9000`). |
| `MEALIE_PUBLIC_URL` | Mealie address your browser can open, used for links. |
| `SECRET_KEY` | Unused until the AI step. |
| `BASE_URL` | homeplate's public URL; `https` turns on the cookie `Secure` flag. |
| `TZ` | Time zone that decides what "today" is (default `UTC`). |
| `DATA_DIR` | Where the database and photos live (default `/data`). |

## Tests

    python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/pytest -q
