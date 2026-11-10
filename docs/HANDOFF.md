# Homeplate: where things stand

Written at the end of the session on 2026-11-10 (US Eastern). Read this first when resuming.

## What Homeplate is

A self-hosted, phone-first **chat window for the Mealie recipe manager**, for the owner plus a few friends and family on one Unraid server. You sign in with your Mealie account and talk to an AI assistant that can search the web for recipes, show them as cards, add one to Mealie with a tap, and answer questions about your saved recipes. Everything else is done in Mealie itself. The owner uses the app and does not maintain the code.

**This is a change of direction made on 2026-11-10.** Homeplate used to also have a calorie diary, weight log, workouts, cooking streaks, a recipe page with photo galleries, and plans for its own shopping list and recipe pages. After trying the assistant the owner said: "homeplate was just a chat window for mealie, and I do everything else in mealie", and, asked whether to keep the tracking, "chat only". Those pages are removed. Their data is not: see "Old data" below.

## State of the code

`main` has the chat-only app once PR 8 is merged (check `gh pr list` and `git log origin/main`). 269 tests pass locally and in CI. The image `ghcr.io/bbergle/homeplate:latest` is published on every push to `main`.

| PR | What it did |
|---|---|
| 1 to 5 | The original app: sign-in with Mealie accounts, Today diary, Me page, photos and galleries, invites, UI refresh, account requests and admin, workouts. Most of this was removed by PR 8 |
| 6 | Assistant piece 1: each person's own OpenRouter key and model (stored encrypted), and the Ask tab: questions answered with web search and sources |
| 7 | Assistant piece 2: asking for recipes returns cards with a photo and an Add button that imports the recipe into Mealie; the assistant can look up the person's saved recipes |
| 8 | Chat only: removed Today, workouts, Me, the recipe page, galleries and the Order placeholder. Home is the chat. New Settings page (AI key and model, Invite, Admin, Sign out). An added card links to the recipe in Mealie. A Not found page with a way back to the chat |

What is in the app now:

- `app/auth.py` sign-in and sessions; `app/main.py` middlewares (same-origin guard, 20 MB body limit), error pages and the Not found page.
- `app/ask.py` the chat, the answer loop (up to six model rounds), cards and the Add route; `app/asktools.py` the assistant's tools; `app/ai.py` the OpenRouter client and key encryption; `app/webimg.py` the guarded fetch of card photos.
- `app/settings.py` the Settings page; `app/invite.py` and `app/access.py` invites, account requests and admin.
- `app/mealie.py` the Mealie client; `app/db.py` the schema (unchanged by PR 8).

### Old data

PR 8 deleted pages, not data. The tables `entries`, `weights`, `workouts`, `photos` and the goal columns on `users` are still created and still hold whatever was logged, and the `photos` folder under the data folder is untouched. Nothing reads them now. If the owner wants tracking back, the code is in git history before PR 8 (`git show 419b0d2:app/today.py`, and so on).

## Checked, and not checked

- `node scripts/ask-check.mjs` drives a real headless Chrome over the DevTools protocol against the local stack with the real OpenRouter key. It passed 22 of 22 on the chat-only build on 2026-11-10: sign-in lands on the chat; a recipe search returns cards with photos in 9 to 18 s; Add imports exactly once and the card links to the recipe in Mealie; a question about saved recipes is answered; no sideways overflow at 375, 390 and 430 px in light and dark.
- The photo fetch was tried against the real network: real photos fetched; localhost, private addresses, a public name pointing at 127.0.0.1, a web page and an SVG refused.
- Not checked by anyone: a physical phone. The Chrome extension was not connected in this session, which is why the script exists.

## Decisions the owner made (do not reopen without cause)

- **Homeplate is a chat window for Mealie and nothing else** (2026-11-10). No recipe pages, shopping list pages, meal plan pages or tracking in Homeplate. Do not rebuild Mealie's screens.
- Mealie is the recipe engine and the login source.
- Nothing is public. Only people with an account see anything.
- New accounts: an admin invites directly, or switches on account requests and approves each one. (Kept in Homeplate for now. The owner was told these could move to Mealie too and has not asked for that.)
- The assistant proposes and the owner taps to confirm any change.
- Each person uses their own AI key. OpenRouter first.
- Search goes through OpenRouter's search tool with the Parallel engine and low reasoning effort (about 5 to 18 s and 0.1 to 0.15 cents a question). A local SearXNG was tried and is the fallback, not built.
- Kroger, not Meijer, if ordering is ever built (Meijer has no API and forbids automation).
- No Reddit API. Reddit comes through web search.
- Standing permission: open pull requests and merge them into `main` in this repo without asking, when checks are green. (Not for other repos; not for force pushes or failing checks. Deleting branches is blocked by the tool's own safety rule: leave them or ask.)
- Execution style for build work: a fresh agent per task, a review after each task, and a whole-branch review before merging.

## What is next, in order

### 1. The assistant, piece 3 (needs a new plan)

The design is `docs/superpowers/specs/2026-11-09-assistant.md`. Read its "Change of direction" section first: the food-entry and workout cards, the Today look-up and the buttons on Today and the recipe page no longer apply. What is left for piece 3, all through the chat:

- Shopping list: "add the ingredients for that to my list" as a card with an **Add to list** button; look up what is on the list. Mealie's API has what is needed (`/api/households/shopping/...`, including adding a recipe's ingredients to a list).
- Meal plan: propose a plan as a card with **Add to plan**; look up the plan.
- "What can I make with..." through Mealie's `GET /api/recipes/suggestions`.
- Import a recipe from pasted text or a photo (cookbook page, screenshot). A fixed JSON format does not work in a request that also has tools, so the write-out is its own request with no tools.
- Fill in missing nutrition on a recipe (**Save to recipe**).
- Showing the person's own recipes as cards that open in Mealie.

The `proposals` table already holds cards; `kind` is free text. A local database made before the afternoon of 2026-11-10 has an old CHECK on `kind`: drop that table locally before adding kinds.

Later pieces: YouTube search (needs a `YOUTUBE_API_KEY`), direct Claude and Gemini keys.

### 2. Kroger ordering (only if the owner still wants it)

It would now be something asked for in the chat, not a tab. Reference: `docs/research/2026-11-09-kroger-api.md`. Terms that shape it: do not store or cache Kroger data; do not send Kroger data to any third party, including an AI provider; add items only when the user asks.

### 3. Unraid setup

Container template notes, reverse proxy entry, backups of `/data`. Must cover:

- `SECRET_KEY` set to a long random value and kept stable. It signs account-request status links and encrypts saved AI keys; the app refuses to save an AI key while it is unset or a placeholder.
- `BASE_URL` set to the real https address (secure cookie, and the address form posts are accepted from). The reverse proxy must pass the `Host` header through or `BASE_URL` must be right.
- `MEALIE_PUBLIC_URL` set to the address a phone can open Mealie at: the "Open in Mealie" links on cards use it.
- `TZ` (the date the assistant is told), a request body limit of about 20 MB at the proxy, and Mealie's `ALLOW_SIGNUP` kept off.
- Answers are fetched in the background and polled, so they need no long proxy timeout. Add waits on Mealie's import, usually about a second.
- Mealie's `TOKEN_TIME` raised: Mealie sign-ins last 48 hours even when renewed.
- The container's data folder must be writable by the image's non-root user. Do not delete its `photos` folder (old data, kept).
- Only Mealie 3.30 was tested.

## Known small issues (none blocking)

- Cards: if Mealie is unreachable by timing out on connect (rather than refusing the connection), every card says "Mealie can't import this page." instead of the "can't reach your recipe library" message. One line in `asktools.recipe_cards` (add `httpx.ConnectTimeout` to the check).
- Cards: an import that takes Mealie longer than 60 seconds shows "Can't reach Mealie. Try again."; tapping again can then make a second copy.
- Cards: a card stays on "Still adding" for good if the server stops in the middle of an import.
- Cards: photo files of old cards are only removed by New chat (640 px JPEGs, a few per recipe search).
- Cards: the recipe page behind a card is fetched by Mealie, not Homeplate, so Mealie's own address rules apply to it (see the design, "Privacy and limits").
- Assistant: the number of look-ups the model may ask for in one round is limited only by the answer size limit.
- Ask: once a chat passes 20 messages, the history sent to the model starts with one of its own replies. Fine on OpenRouter today; check before adding direct Claude keys.
- Ask: pressing New chat while an answer is being fetched lets one person run several model calls at once.
- Ask: when an answer has source links, a line starting "Source:" in the middle of the answer cuts everything after it.
- Ask: a very long single conversation is sent whole on every 3 second poll and opens at its oldest message.
- Ask: screen readers may not announce a new answer.
- AI settings: an odd reply from OpenRouter's model list (a model with no `architecture`) would give an error page on save.
- Accounts: a demoted admin still sees the Admin button and pending count until their next sign-in (the admin pages themselves re-check live). A Mealie refusal during invite or approval shows "Can't reach Mealie". While account requests are on, anyone can fill the 20-request queue.
- The sign-in page's tagline, "Cook at home. Keep the change.", refers to the removed savings feature. Left for the owner to decide.
- Dependencies are unpinned (`>=`); local Python is 3.15, CI and the image use 3.12. `pillow-heif` is installed but unused until photo input is built.

## Running it locally

```
cd ~/Dev/homeplate
docker compose up -d --build        # app on :8000, test Mealie on :9925
.venv/bin/pytest -q                 # 269 passed
node scripts/ask-check.mjs          # live check in a headless Chrome; asks real questions (a fraction of a cent)
```

- Test sign-in: Mealie's default admin, `changeme@example.com` / `MyPassword`. The compose Mealie has no data volume, so recreating that container resets it. Do not recreate it casually: the owner has test recipes in it.
- `~/Dev/homeplate/.env` holds the owner's `OPENROUTER_API_KEY` and the `SECRET_KEY` the local compose app uses. Never print it. The test admin already has that key saved, encrypted, in `data/homeplate.db`.
- The OpenRouter key has a $25 monthly cap. On 2026-11-10 the account showed $0 of purchased credit and requests without a small `max_tokens` were refused; the app always sends `max_tokens`.
- Screenshots at phone width, light and dark: `WIDTH=390 scripts/shots.sh /some/out/dir /ask /settings`. It signs in as the test admin and strips htmx.
- Mealie's API description for checking endpoints: `curl http://localhost:9925/openapi.json`.

## Lessons worth keeping

- Check screenshots at several widths (375, 390, 430), and in the state that shows the thing being changed.
- A form must be submitted by a real browser before it is called working. `scripts/ask-check.mjs` is how, when the Chrome extension is not connected.
- A broad CSS selector on a shared class name restyled unrelated elements twice. Give new elements their own class and add a test.
- Verify a third-party API's availability, cost and behaviour live before building on it. The default search engine was 10 times slower and 30 times dearer than the one now used; only a live test showed it.
- Fetching anything from an address the model or a web page supplied needs a guard that resolves once, checks every address, and connects to the address it checked, with a new client per request. The first version looked the name up twice.
- When deleting a feature, check which tests of kept behaviour lived in its test file. Three security tests went out with the diary's tests and had to be restored.
- The owner prefers to see something working and react to it over answering design questions. Offer a recommendation and a default, and build.
