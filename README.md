# homeplate

A small self-hosted chat assistant for the [Mealie](https://mealie.io) recipe manager. Sign in with your Mealie account, then ask for recipe ideas. The assistant finds recipes on the web and you add them to Mealie with a tap. You can also ask about the recipes you have already saved.

The assistant runs on your own OpenRouter key. Add it on the Settings page. Everything else, such as browsing and cooking recipes, you do in Mealie.

## Run locally

    docker compose up

homeplate is on http://localhost:8000 (`/healthz`), Mealie on http://localhost:9925.

## Configuration

| Variable | Meaning |
| --- | --- |
| `MEALIE_URL` | Where homeplate reaches Mealie (default `http://mealie:9000`). |
| `MEALIE_PUBLIC_URL` | Mealie address your browser can open. The "Open in Mealie" links on added recipes use it. Without it those links are left out. |
| `SECRET_KEY` | Signs the private status links for account requests. Set a long random value and keep it the same. If it is not set, the app falls back to a built-in placeholder. That only lets someone make a fake "request sent" page appear and exposes nothing, but you should still set it. It also encrypts saved AI keys: the app will not save an AI key while it is unset or a placeholder (`dev`, `change-me`), and changing it means everyone re-enters their key. |
| `BASE_URL` | homeplate's real public address, such as `https://plate.example.com`. An `https` address turns on the cookie `Secure` flag. It is the address used in join links. Form posts are accepted only from this address or the address the request arrived on. |
| `TZ` | Time zone that decides the date the assistant is told (default `UTC`). |
| `DATA_DIR` | Where the database and photos live (default `/data`). The `cards` folder holds recipe card photos. The `photos` folder is from earlier versions and is kept. |

## Accounts

Nothing in homeplate is public: new people need an account. Admins, and users Mealie lets invite (the "can invite" permission), can create an invite link at `/invite`, for their own household or, for admins, a new one. The link opens a public form at `/join/<token>`; it is single-use and creates a Mealie account, then signs the new user in.

An admin can also switch on account requests (Settings, then Admin; off by default). While it is on, the sign-in screen shows "Create account", which asks for a name, email and optional note, never a password. The requester gets a private status page; an admin approves (choosing the household) or declines each request on `/admin`. Approval creates a single-use invite and the status page then leads into the join form. Mealie's own open sign-up can stay off.

Anyone can type any name and email into the request form, and homeplate does not check them. Before you approve, check with the person that the request is really theirs. Otherwise a stranger could get an account in someone else's name.

While account requests are on, at most 20 requests can wait at once. Further requests are silently ignored until you decide some. Turn the switch off when you are not expecting anyone.

## Upgrading from an earlier version

Earlier versions had a diary, weight, workouts and photos. That data stays in the database and in the `photos` folder under the data folder. It is no longer shown. Do not delete it if you might want it back.

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
