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
| `BASE_URL` | homeplate's public URL; `https` turns on the cookie `Secure` flag. Form posts are accepted only from this address or the address the request arrived on. |
| `TZ` | Time zone that decides what "today" is (default `UTC`). |
| `DATA_DIR` | Where the database and photos live (default `/data`). |

## Sharing

Any signed-in user can create a public link for a recipe from its gallery page (`/r/<id>`). Anyone with the link, no account needed, sees the recipe and everyone's non-private photos of it, nothing about who cooked it. "Stop sharing" kills the link. No extra Mealie setup is needed.

A share link's token is a Mealie share token. If Mealie itself is reachable from the internet, someone holding a share link who knows the Mealie address can read that recipe's full Mealie record (including the names of people who commented on it) through Mealie's own API.

## Invites

Admins, and users Mealie lets invite (the "can invite" permission), can create an invite link at `/invite`, for their own household or, for admins, a new one. The link opens a public form at `/join/<token>`; it is single-use and creates a Mealie account, then signs the new user in. Mealie's own open sign-up can stay off.

## Tests

    python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/pytest -q
