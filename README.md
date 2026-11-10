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

Nothing in homeplate is public: only people with an account can see any recipe, photo or user detail. The recipe page (`/r/<id>`) shows the full recipe and everyone's non-private photos. Its "Link to this recipe" card is an ordinary link; without an account it leads to the sign-in screen and, after signing in, back to that recipe.

## Invites

Admins, and users Mealie lets invite (the "can invite" permission), can create an invite link at `/invite`, for their own household or, for admins, a new one. The link opens a public form at `/join/<token>`; it is single-use and creates a Mealie account, then signs the new user in. Mealie's own open sign-up can stay off.

## Tests

    python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/pytest -q
