# Homeplate: where things stand

Written at the end of the session on 2026-11-09 (US Eastern evening). Read this first when resuming.

## What Homeplate is

A self-hosted, phone-first companion app for the Mealie recipe manager, for the owner plus a few friends and family on one Unraid server. Purpose: stop ordering delivery, cook at home, lose weight, see money saved. Mealie holds recipes, the meal plan and the shopping list; Homeplate adds a calorie diary, weight log, workouts, weekly cooking streaks, recipe photo galleries, and (planned) an AI assistant and Kroger ordering. The owner uses the app and does not maintain the code.

## State of the code

`main` (commit `2eb2583`) has everything built (193 tests at the time). The image `ghcr.io/bbergle/homeplate:latest` is published on every push to `main`.

| PR | What it added |
|---|---|
| 1 | Sign-in with Mealie accounts, Today diary (meals, food, weight), Me page (weekly goal, streak, achievements, savings), CI and image publishing |
| 2 | iPhone HEIC photos, per-recipe photo galleries with a private flag, invite links that create a Mealie account, same-origin guard on form posts |
| 3 | UI refresh from a researched design spec: tokens, icon tab bar, calorie ring, badge grid, restyled pages |
| 4 | Accounts only: public share pages removed; member recipe page; admin switch for account requests; request form, status page, admin approve or decline |
| 5 | Workouts: manual logging, calorie estimate, net calories on Today, share-of-calories setting |

Branch `assistant` (not merged) holds the design documents, `scripts/shots.sh`, and assistant piece 1: the OpenRouter client (`app/ai.py`), encrypted key and model settings on the Me page, and the Ask tab with web search and sources (`app/ask.py`). 256 tests pass. Live check on 2026-11-10 against the real service: three questions answered in 5 to 10 s at about 0.1 cents each, sources shown, a second model works, and a fixed JSON format does not work together with search (see the design, "Live test results"). One fix came out of it (bare links in answers).

Checked in a real browser: a headless Chrome was driven over the DevTools protocol against the local app (real htmx, real form posts), 21 of 21 checks passing. They covered sign-in; the AI settings form refusing a fake key with "OpenRouter rejected that key." and keeping the real one; New chat clearing the conversation; the waiting bubble appearing and the form disabling; the answer swapping in without a reload (6.1 s); a reload mid-wait still ending with the answer (8.0 s); sources rendered as `target="_blank" rel="noopener noreferrer"` links; and no sideways overflow and 31 px between the last button and the tab bar at 375, 390 and 430 px, light and dark. Not checked: a physical phone. The "run until OpenRouter answers 402" gate never triggered, so the out-of-credit path was only tested with mocked responses.

Next: whole-branch review, pull request to `main`, show the owner, then piece 2 of the assistant (look-up tools, proposal cards).

## Not yet verified by anyone

- Use on a real phone. Every flow was exercised by script or headless Chrome; layouts were checked from screenshots at 375, 390 and 430px.
- The recipe search results list on Today has never appeared in a screenshot (the screenshot method strips htmx).
- A real iPhone HEIC or multi-picture JPEG upload (only generated files were tested).
- Hero totals of 10,000 or more in the eaten/burned line.

## Decisions the owner made (do not reopen without cause)

- Mealie is the recipe engine and the login source.
- Kroger, not Meijer, for ordering (Meijer has no API and forbids automation).
- Nothing is public. Only people with an account see anything. A recipe link is a plain link into the app.
- New accounts: an admin invites directly, or switches on account requests and approves each one. Approval alone is enough: no confirmation code, no email verification (asked and answered).
- Calorie diary and weight log are in. Workouts are typed in by hand (no Strava or Garmin import), with the app estimating calories.
- No Grocy. "What do I have" is handled by the assistant from what the owner says or a fridge photo, with no stored inventory.
- No Reddit API. Reddit recipes come through the assistant's web search, or by pasting a link's text or a screenshot.
- The assistant proposes and the owner taps to confirm any change. Kroger cart filling stays in code.
- The assistant may send what the person types, their photos, and looked-up recipes, plan, list and diary totals to the AI provider they chose. Weight is not sent.
- Standing permission: open pull requests and merge them into `main` in this repo without asking, when checks are green. (Not for other repos; not for force pushes or failing checks.)
- Execution style chosen for build work: a fresh agent per task, a review after each task, and a whole-branch review before merging.

## What is next, in order

### 1. The assistant (step 3): WAITING FOR THE OWNER

The owner chose to pause before approving the design. Do not write assistant code until they approve it.

- Design: `docs/superpowers/specs/2026-11-09-assistant.md` (on branch `assistant`).
- Provider request formats and what is verified: `docs/research/2026-11-09-ai-providers.md`.
- Needed from the owner: approval of the design, and an OpenRouter key in `~/Dev/homeplate/.env` as `OPENROUTER_API_KEY` (never pasted into chat). Optional: `YOUTUBE_API_KEY`.
- First task once approved: a live test with the real key of the five unverified points listed at the end of the design (OpenRouter's search tool alongside the app's tools; photo plus search in one request; how well searches read Reddit; YouTube API cost; fixed-format output together with tools). Then write the implementation plan for piece 1.
- Requirements gathered for it, all in the design: tools and tap-to-confirm cards; recipe finding on the web, Reddit (via search) and YouTube (description or linked recipe; video attached as a link; no transcripts); photos on recipe cards; "what do I have" through Mealie's `GET /api/recipes/suggestions`; import from photo, text or link; calorie estimate from a meal photo; workout calories from a description; filling missing recipe nutrition; OpenRouter first, then Claude and Gemini direct.

### 2. Kroger ordering (step 4)

- Reference: `docs/research/2026-11-09-kroger-api.md`.
- First task: confirm with a real Kroger developer account what the docs could not: that the API is free, the exact cart call (`PUT /v1/cart/add` with `{"items":[{"upc","quantity","modality"}]}` comes from a community client, not Kroger), scope names, redirect rules, and that Fort Wayne stores offer pickup. Carts cannot be tested in Kroger's test environment.
- Terms that shape the design (verified): do not store or cache search or cart data; do not send Kroger data to any third party, including an AI provider; add items only when the user asks; no price comparison with other retailers; the app's name must not contain "Kroger".

### 3. Unraid setup (step 5)

Container template notes, reverse proxy entry, backups of `/data`. Must cover:
- `SECRET_KEY` set to a long random value and kept stable (it signs account-request status links and will encrypt AI keys).
- `BASE_URL` set to the real https address (secure cookie, links, and the address form posts are accepted from). The reverse proxy must either pass the `Host` header through or `BASE_URL` must be right.
- `TZ`, a request body limit of about 20 MB at the proxy, and Mealie's `ALLOW_SIGNUP` kept off.
- Mealie's `TOKEN_TIME` raised (hours): Mealie sign-ins last 48 hours even when renewed, so longer gaps mean signing in again.
- Mealie serves recipe images by id without sign-in. If "nothing public" must hold end to end, keep Mealie itself off the public internet.
- The container's data folder must be writable by the image's non-root user.
- If the owner's existing Mealie is older than 3.30 (especially before version 2), check it before deploying; only 3.30 was tested.

### Smaller things raised and not done

- Logging or editing entries for past days (a meal logged after midnight lands on the next day). Raised twice; the owner has not asked for it.
- A week view of the meal plan inside Homeplate (offered; not requested). Mealie's own calendar feed already works for Apple Calendar: all-day events titled like "Dinner: Recipe" with a link to the recipe in Mealie.
- Names on other people's gallery photos (currently none, by design choice).
- Entry removal has no confirmation step.

## Known small issues (deferred by reviews, none blocking)

- The Today ring can show full when a few calories remain (rounding).
- Validation messages for settings use raw field names ("workout pct must be ...").
- A failed form submit clears what was typed (food, workout forms).
- Entry and photo "more" menus all announce the same label to screen readers.
- A demoted admin still sees the Admin button and pending count until their next sign-in (the admin pages themselves re-check live).
- A Mealie refusal during invite or approval shows "Can't reach Mealie".
- While account requests are on, anyone can fill the 20-request queue; later requests are silently ignored until some are decided.
- Creating a new household and then failing to create the invite leaves an empty household in Mealie.
- Dependencies are unpinned (`>=`); local Python is 3.15, CI and the image use 3.12.
- One StarletteDeprecationWarning about httpx in the test output.

## Running it locally

```
cd ~/Dev/homeplate
docker compose up -d --build        # app on :8000, test Mealie on :9925
.venv/bin/pytest -q                 # 193 passed
```

- Test sign-in: Mealie's default admin, `changeme@example.com` / `MyPassword`. The compose Mealie has no data volume, so recreating that container resets it.
- The local Mealie and `data/homeplate.db` contain leftover test data (users, a recipe, requests, demo weights).
- Screenshots at phone width, light and dark: `WIDTH=390 scripts/shots.sh /some/out/dir / /me /admin`. It signs in as the test admin, strips htmx, and cannot open `<details>`.
- Mealie's API description for checking endpoints: `curl http://localhost:9925/openapi.json`.

## Lessons from this session worth keeping

- Check screenshots at several widths (375, 390, 430), and in the state that shows the thing being changed. Two regressions shipped past a builder because the screenshot showed the wrong state or width.
- A public form must be submitted by a real browser before it is called working. `Referrer-Policy: no-referrer` makes browsers send `Origin: null`, which the same-origin guard rejects; curl never shows this.
- A broad CSS selector on a shared class name (`.hero`, `.hint`) restyled or hid unrelated elements twice. Give new elements their own class and add a test.
- Verify a third-party API's availability and cost in its own docs before proposing it. The Reddit API was first described as a free two-minute credential; it requires approval and may be closed to new apps.
- When two branches are built in parallel, have the final reviewer simulate the merge and write down the resolution. One natural-looking resolution would have brought back a dropped table.
