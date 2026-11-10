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
| `SECRET_KEY` | Signs the private status links for account requests. Set a long random value and keep it the same. If it is not set, the app falls back to a built-in placeholder. That only lets someone make a fake "request sent" page appear and exposes nothing, but you should still set it. |
| `BASE_URL` | homeplate's real public address, such as `https://plate.example.com`. An `https` address turns on the cookie `Secure` flag. It is the address used in recipe and join links. Form posts are accepted only from this address or the address the request arrived on. |
| `TZ` | Time zone that decides what "today" is (default `UTC`). |
| `DATA_DIR` | Where the database and photos live (default `/data`). |

## Sharing

Nothing in homeplate is public: only people with an account can see any recipe, photo or user detail. The recipe page (`/r/<id>`) shows the full recipe and everyone's non-private photos. Its "Link to this recipe" card is an ordinary link; without an account it leads to the sign-in screen and, after signing in, back to that recipe.

## Workouts

Workouts are typed in. If you give a calorie number from your own device, it is used as given. Otherwise the app estimates it from the activity, effort, minutes and your latest logged weight. The day's calories are shown net of what was burned, and a setting in Me controls what share of workout calories counts.

## Accounts

Nothing is public: new people need an account. Admins, and users Mealie lets invite (the "can invite" permission), can create an invite link at `/invite`, for their own household or, for admins, a new one. The link opens a public form at `/join/<token>`; it is single-use and creates a Mealie account, then signs the new user in.

An admin can also switch on account requests (Me, then Admin; off by default). While it is on, the sign-in screen shows "Create account", which asks for a name, email and optional note, never a password. The requester gets a private status page; an admin approves (choosing the household) or declines each request on `/admin`. Approval creates a single-use invite and the status page then leads into the join form. Mealie's own open sign-up can stay off.

Anyone can type any name and email into the request form, and homeplate does not check them. Before you approve, check with the person that the request is really theirs. Otherwise a stranger could get an account in someone else's name.

While account requests are on, at most 20 requests can wait at once. Further requests are silently ignored until you decide some. Turn the switch off when you are not expecting anyone.

## Deploying

- Set `SECRET_KEY` to a long random value and do not change it. If it changes, a "request sent" page for a request that was never stored stops opening. Real requests keep working.
- Set `BASE_URL` to the real https address.
- Keep Mealie's own `ALLOW_SIGNUP` switched off.
- "Nothing is public" covers homeplate only. Mealie serves recipe images by id without a sign-in. If that matters to you, keep Mealie itself off the public internet. Only homeplate, and people on your network or VPN, should be able to reach it.

## Upgrading

- Older versions had public share links. They created Mealie share tokens that are valid for ten years, and this version no longer tracks them. They can still be opened through Mealie's own address. To remove them, list them and delete each one with Mealie's API. Replace `MEALIE`, `TOKEN` and `ID`. `MEALIE` is your Mealie address (for example `http://localhost:9925`). `TOKEN` comes from Mealie: open your profile, choose "API Tokens", and create one. `ID` is the id of each link in the first command's output:

      curl -H "Authorization: Bearer TOKEN" MEALIE/api/shared/recipes
      curl -X DELETE -H "Authorization: Bearer TOKEN" MEALIE/api/shared/recipes/ID

- An admin who is already signed in sees the Admin button only after signing out and in again. They can also open `/admin` directly.

## Tests

    python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/pytest -q
