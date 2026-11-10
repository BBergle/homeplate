# Homeplate: where things stand

Written at the end of the session on 2026-11-09 (US Eastern evening). Read this first when resuming.

## What Homeplate is

A self-hosted, phone-first companion app for the Mealie recipe manager, for the owner plus a few friends and family on one Unraid server. Purpose: stop ordering delivery, cook at home, lose weight, see money saved. Mealie holds recipes, the meal plan and the shopping list; Homeplate adds a calorie diary, weight log, workouts, weekly cooking streaks, recipe photo galleries, and (planned) an AI assistant and Kroger ordering. The owner uses the app and does not maintain the code.

## State of the code

`main` has everything built, including assistant pieces 1 and 2. 356 tests pass locally and in CI. The image `ghcr.io/bbergle/homeplate:latest` is published on every push to `main`.

| PR | What it added |
|---|---|
| 1 | Sign-in with Mealie accounts, Today diary (meals, food, weight), Me page (weekly goal, streak, achievements, savings), CI and image publishing |
| 2 | iPhone HEIC photos, per-recipe photo galleries with a private flag, invite links that create a Mealie account, same-origin guard on form posts |
| 3 | UI refresh from a researched design spec: tokens, icon tab bar, calorie ring, badge grid, restyled pages |
| 4 | Accounts only: public share pages removed; member recipe page; admin switch for account requests; request form, status page, admin approve or decline |
| 5 | Workouts: manual logging, calorie estimate, net calories on Today, share-of-calories setting |
| 6 | Assistant piece 1: each person's own OpenRouter key and model on the Me page (stored encrypted), and the Ask tab: questions answered with web search and sources. Also the assistant design, research notes and these handoff notes |
| 7 | Assistant piece 2: asking for recipes returns cards with a photo and an Add button that imports the recipe into Mealie; the assistant can look up the person's saved recipes |

PR 6 (merged 2026-11-10) brought in the design documents, `scripts/shots.sh`, and assistant piece 1: the OpenRouter client (`app/ai.py`), encrypted key and model settings on the Me page, and the Ask tab with web search and sources (`app/ask.py`). 260 tests pass. Live check on 2026-11-10 against the real service: three questions answered in 5 to 10 s at about 0.1 cents each, sources shown, a second model works, and a fixed JSON format does not work together with search (see the design, "Live test results"). One fix came out of it (bare links in answers).

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

### 1. Shopping lists in Homeplate: DESIGN IN PROGRESS

On 2026-11-10 the owner asked to see and edit Mealie's shopping lists inside Homeplate. The Order tab is still a placeholder. Mealie stays the one list; Kroger ordering (below) will later send that list to a cart. Mealie's API has what is needed: lists (create, rename, delete), items (add, edit, tick, remove, bulk), and adding a recipe's ingredients to a list (`/api/households/shopping/...`). Branch `shopping-lists`. Nothing is designed or built yet: the owner had been asked how they use the list today and had not answered.

### 2. The assistant (step 3): pieces 1 and 2 merged, pieces 3 to 5 remain

The owner approved the design on 2026-11-10 and asked for the cards the same day after trying piece 1. Each piece is shown to the owner before the next starts.

- Design, with the live test results: `docs/superpowers/specs/2026-11-09-assistant.md`. Plan for piece 1 (done): `docs/superpowers/plans/2026-11-10-assistant-piece1.md`.
- Next is piece 3: the other cards (meal plan, shopping list, food entry, workout, recipe nutrition), their look-ups, photo input, and importing a recipe from pasted text or a photo. It needs its own plan. Plans so far: `docs/superpowers/plans/2026-11-10-assistant-piece1.md` and `-piece2.md`. The `proposals` table already holds cards (`kind` is free text); a local database made before 2026-11-10 afternoon has an old CHECK on `kind`, so drop that table locally before adding kinds.
- Settled by live tests: OpenRouter's search tool works alongside the app's own tools and with a photo in the same request. A fixed JSON format does not work in a request that also has tools (the format is ignored), so fixed-format requests are their own request with no tools.
- Search settings (owner agreed): OpenRouter's search tool with the Parallel engine in turbo mode and low reasoning effort. About 5 to 10 s and 0.1 cents a question. The default engine took 20 to 105 s and 1 to 4 cents. A local SearXNG was tried and works (1 to 3 s, free) but DuckDuckGo blocked it within a minute; it is the fallback, not built.
- The owner's OpenRouter key is in `~/Dev/homeplate/.env` as `OPENROUTER_API_KEY` (never print it). The key has a $25 monthly cap. On 2026-11-10 the account showed $0 of purchased credit, and requests without a small `max_tokens` were refused; the app always sends `max_tokens`. `.env` also holds the `SECRET_KEY` the local compose app uses.
- Optional, before piece 4: a `YOUTUBE_API_KEY` in the same file.
- Real-browser check without the Chrome extension: `node scripts/ask-check.mjs` drives a headless Chrome over the DevTools protocol against the local stack (asks real questions, adds one recipe through a card and deletes it again). It passed 22 of 22 on 2026-11-10. A physical phone is still unchecked.

### 3. Kroger ordering (step 4)

- Reference: `docs/research/2026-11-09-kroger-api.md`.
- First task: confirm with a real Kroger developer account what the docs could not: that the API is free, the exact cart call (`PUT /v1/cart/add` with `{"items":[{"upc","quantity","modality"}]}` comes from a community client, not Kroger), scope names, redirect rules, and that Fort Wayne stores offer pickup. Carts cannot be tested in Kroger's test environment.
- Terms that shape the design (verified): do not store or cache search or cart data; do not send Kroger data to any third party, including an AI provider; add items only when the user asks; no price comparison with other retailers; the app's name must not contain "Kroger".

### 4. Unraid setup (step 5)

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

- Ask: once a chat passes 20 messages, the history sent to the model starts with one of its own replies. Fine on OpenRouter today; check before adding direct Claude keys.
- Ask: pressing New chat while an answer is being fetched lets one person run several model calls at once.
- Ask: when an answer has source links, a line starting "Source:" in the middle of the answer cuts everything after it.
- Ask: the model sometimes writes short "-" lists; they show as plain text.
- Ask: a very long single conversation is sent whole on every 3 second poll and opens at its oldest message.
- Ask: screen readers may not announce a new answer.
- AI settings: an odd reply from OpenRouter's model list (a model with no `architecture`) would give an error page on save.

- Cards: if Mealie is unreachable by timing out on connect (rather than refusing the connection), every card says "Mealie can't import this page." instead of the "can't reach your recipe library" message. One line in `asktools.recipe_cards` (add `httpx.ConnectTimeout` to the check).
- Cards: an import that takes Mealie longer than 60 seconds shows "Can't reach Mealie. Try again."; tapping again can then make a second copy.
- Cards: a card stays on "Still adding" for good if the server stops in the middle of an import.
- Cards: photo files of old cards are only removed by New chat (640 px JPEGs, a few per recipe search).
- Cards: the recipe page behind a card is fetched by Mealie, not Homeplate, so Mealie's own address rules apply to it (see the design, "Privacy and limits").
- Assistant: the number of look-ups the model may ask for in one round is limited only by the answer size limit.

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
