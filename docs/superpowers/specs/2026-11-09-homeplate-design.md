Superseded in part: public share pages were removed on 2026-11-09. See `2026-11-09-access.md`.

# Homeplate: a companion app for Mealie (working name, my call)

## Context

The owner orders DoorDash when the kitchen is empty and the dishes feel like too much. Today they
walk Meijer with no plan. In six months they want to be cooking at home most nights, eating better,
losing some weight, and seeing the money saved. The app is for them plus a few friends and family on
one self-hosted instance (Unraid, Docker, existing reverse proxy and domain). It is not a public
platform. The owner will use it, not maintain the code, so the stack is chosen for being boring.

## Decisions made by the owner

- **Mealie is the recipe engine.** Recipes (manual entry and paste-a-link import), weekly meal plan
  and shopping list stay in Mealie's own UI. Everyone is a user in one Mealie group.
- **Kroger, not Meijer, for ordering.** Meijer has no official API, sits behind Akamai and forbids
  automation. Kroger has an official free API with store prices and add-to-cart.
- **No Instagram-style feed.** Sharing is a public link per recipe that anyone can open without an
  account. It shows the recipe and every photo of that recipe uploaded by any user on the instance.
- **Calorie diary and weight log are in.**
- **The assistant can import recipes on request**, from a photo (cookbook page, recipe card,
  screenshot), pasted text or a link, and save them into Mealie.
- **New people get their Mealie account created from this app**, by invite link (my call: invite
  only, no open sign-up, because the app is internet-facing).
- **AI is optional per user.** Calorie estimates from meal photos and the assistant only work for a
  user who has supplied an API key. Providers: OpenRouter, Gemini and Claude.

## Calls I made (owner has not confirmed each one)

- Stack: Python 3.12, FastAPI, Jinja2 templates with htmx, SQLite via stdlib `sqlite3`, Pillow,
  httpx. One container, one `/data` volume (database and photos). No JS build step.
- Sign-in uses Mealie credentials (app posts them to Mealie's token endpoint); no separate accounts.
- Streaks are weekly: goal of N home meals per week (default 3), leftovers count, a missed week is
  forgiven if the next week reaches goal + 1.
- Users do not see each other's diary, weight or streaks. The only cross-user content is recipe
  photos.
- A photo can be marked private by its uploader, which keeps it off the recipe gallery and share
  page. Default is shared.
- Share page is no-index, uses a random token, can be revoked, and photos have EXIF stripped.
- AI keys are per user, stored encrypted (Fernet, key from `SECRET_KEY` env).
- Mealie users sign in with passwords (not SSO).
- Streak details: weeks run Monday to Sunday in the `TZ` timezone; only `cooked` and `leftovers`
  count; the current week never counts as missed; two missed weeks in a row reset the streak.
- Achievements are five fixed ones: first cook, 10 meals, 50 meals, 4-week streak, 5 different
  recipes.
- Left out: Meijer, leaderboards, in-app checkout, barcode scanning, push notifications, offline
  mode, viewing friends' streaks. Add when asked for.

## Limits found in review (checked against vendor docs)

- **Kroger forbids storing data derived from product searches or cart items.** So the app cannot
  remember which product you picked for "milk". Every order re-searches each list item at your
  store, preselects the top match, and you swap any wrong ones on the page before sending. Only the
  chosen store ID is kept.
- **Kroger's cart is add-only.** The app cannot read or empty it. After "Add all" the button becomes
  a "Sent" state so a second tap cannot double the order; removing items happens in the Kroger app.
- **Not confirmed from Kroger's docs** (JS-rendered pages): that the API is free, the exact cart
  path and body, and scope names. Step 4 starts by confirming these with a real developer account.
- Kroger refresh tokens are single-use and last six months: store the new one on every refresh and
  show "Reconnect Kroger" if a refresh fails. OAuth uses PKCE and `state`.
- Mealie sign-in tokens last 48 hours by default: refresh on each visit via `/api/auth/refresh`,
  fall back to the login page on 401.

## Architecture

```
phone browser ──> reverse proxy ──> homeplate (FastAPI, :8000) ──> Mealie API (internal URL)
                                         │                    ──> Kroger API
                                         │                    ──> Gemini / Claude API (user's key)
                                         └── /data: homeplate.db, photos/
```

Env: `MEALIE_URL`, `MEALIE_PUBLIC_URL` (for links), `SECRET_KEY`, `KROGER_CLIENT_ID`,
`KROGER_CLIENT_SECRET`, `BASE_URL`, `TZ` (e.g. `America/Indiana/Indianapolis`, so "today" and week
boundaries are local).

Mealie endpoints used (verified against v3.30 spec): `POST /api/auth/token` (form: username,
password), `POST /api/auth/refresh`, `GET /api/users/self`, `GET /api/recipes?search=`,
`GET/PATCH /api/recipes/{slug}`, `GET /api/households/mealplans/today`,
`GET /api/households/shopping/lists` and `/items`. Recipe images at
`/api/media/recipes/{id}/images/{file}` need no auth. Nutrition values are nullable strings: parse
the leading number, treat as per serving, prefill and leave editable.

Kroger endpoints: `GET /v1/locations?filter.zipCode.near=`,
`GET /v1/products?filter.term=&filter.locationId=` (client-credentials token; price requires
locationId), cart add via PUT with the user's token. Daily limits (10,000 product, 5,000 cart
calls) are far above this app's use.

### Data (SQLite)

| Table | Columns |
|---|---|
| `users` | mealie_user_id PK, name, weekly_goal, cal_target, protein_target, weight_goal, delivery_cost, home_meal_cost, ai_provider, ai_key_enc, kroger_refresh_token_enc, kroger_location_id |
| `sessions` | id PK, user_id, mealie_token, expires_at |
| `entries` | id, user_id, eaten_at, kind (`cooked`/`leftovers`/`other`), recipe_id, recipe_name, description, calories, protein_g |
| `photos` | id, entry_id, user_id, recipe_id, path, private, created_at |
| `weights` | user_id, date, lbs (PK user_id+date) |
| `shares` | token PK, recipe_id, created_by, revoked |

Streak, achievements and savings are computed from `entries` on each page load; nothing is stored.

### Screens (bottom tab bar, phone-first, 44px touch targets)

- **Today**: calorie and protein totals against targets, today's entries, a large "I cooked" button
  (pick recipe, today's planned meal offered first; photo via
  `<input type="file" accept="image/*">` so camera and library both work; a "show on recipe page"
  checkbox, ticked by default; leftovers toggle), and "Add food"
  (free text plus calories; "Estimate" button appears if the user has an AI key). Weight entry field.
- **Me**: weekly goal progress, week streak, achievements, saved-vs-delivery total, weight trend
  (inline SVG polyline, no chart library), settings (targets, costs, AI provider and key, Kroger
  connect and store).
- **Order**: unchecked Mealie shopping list items (search on the food name, else the note), each
  matched live to a Kroger product with price; swap a match; quantity stepper starting at 1;
  estimated total; "Add all to Kroger cart", which turns into "Sent". Matches live only in the page.
- **Ask**: chat with web search, with a photo attach button. Disabled with a hint if no AI key.
  Recipe import: when the user asks to save a recipe (from an attached photo, pasted text, a link,
  or one the assistant just found), the model calls a single `save_recipe` tool. A link goes to
  `POST /api/recipes/create/url` (`{"url": ...}`); anything else is sent as schema.org Recipe JSON
  (including `nutrition`) in `POST /api/recipes/create/html-or-json` (`{"data": "<json string>"}`).
  Both return the new slug and neither needs Mealie's own AI provider (verified). If the URL import
  returns 400, the model extracts the page and uses the JSON import. Turns with a photo are sent
  without web search. The reply links to the new recipe in Mealie so the user can check it.
- **Invite and join**: an "Invite" button on Me, shown only to Mealie admins. The owner chooses
  "my household" (shared meal plan and shopping list) or "their own household" (named). Using the
  owner's own session token, the app creates the household if needed and a single-use Mealie
  invitation token, and shows a link `{BASE_URL}/join/{token}`. The public join page asks for name,
  email, username and password, registers the user in Mealie with that token, and signs them in.
  No admin credential is stored. From memory, not verified this session: Mealie's
  `POST /api/households/invitations`, `POST /api/users/register` (with `group_token`), and the admin
  household-create call; confirm against the Mealie spec first. If an invitation cannot target a
  new household, fall back to the admin user-create call from the owner's session.
- **Recipe gallery** `/r/{recipe_id}`: all non-private photos of that recipe from all users, link to
  the recipe in Mealie, "Create share link" / "Revoke".
- **Public share** `/s/{token}`: recipe (fetched live from Mealie through a Mealie share token created with the sharer's session, so no service account is needed), photo
  gallery. No login, `noindex`, nothing else about any user. Photos served at
  `/s/{token}/photo/{id}` only when the photo belongs to that recipe and is not private.

Recipes, meal plan and shopping list link out to Mealie.

## Files

```
homeplate/
  Dockerfile  docker-compose.yml (homeplate + mealie for local dev)  requirements.txt  README.md
  app/
    main.py        routes: auth, today, me, recipe gallery, share
    db.py          schema + connection
    mealie.py      login, recipes, today's meal plan, shopping list, update nutrition
    stats.py       streak, achievements, savings (pure functions over entry rows)
    photos.py      save: exif_transpose, downscale to 1600px, strip EXIF, write JPEG
    ai.py          ask(user, messages) and estimate(user, text, image) for openrouter, gemini, claude
    kroger.py      OAuth, store lookup, product search with price, cart add
    order.py       Order tab routes
    templates/     base.html (tab bar), today, me, order, ask, gallery, share, login
    static/        app.css, htmx.min.js, manifest.json, icons
  tests/test_stats.py  tests/test_share.py
```

## Build order

1. **Core**: container, Mealie sign-in, Today (cooked log with photo, manual food entries, weight),
   Me (streak, achievements, savings, weight trend, settings), installable manifest.
2. **Sharing and invites**: recipe gallery, share links, public page, private toggle, invite link
   and join page.
3. **AI**: per-user key, Ask chat with web search, estimate calories from text or meal photo, fill
   missing nutrition on a Mealie recipe, import a recipe from a photo, text or link into Mealie. OpenRouter is built first: it is an OpenAI-style chat
   API, so one key reaches Gemini, Claude and other models, and the user types the model name in
   settings. Its web search option and image input are from memory, not checked this session;
   confirm against OpenRouter's docs before coding. Direct Gemini and Claude keys are the other two
   options. Models are settings, defaults `gemini-3.8-flash` (tool
   `google_search`) and `claude-haiku-5-5` (tool `web_search_20260318`). Estimates use no search and
   chat history lives in the page, not the database.
4. **Kroger**: connect account, pick store, match list to products with prices, add to cart.
   First step is to confirm the current API terms, scopes and the owner's nearest Fort Wayne store.
5. **Unraid**: container template notes, reverse proxy entry, backup of `/data`.

Each step is usable on its own and gets shown to the owner before the next starts.

## Needed from the owner

- Mealie running on Unraid with an admin account.
- A free Kroger developer app (client ID and secret) with the redirect URL
  `{BASE_URL}/kroger/callback`.
- An OpenRouter, Gemini or Claude API key for their own account when step 3 starts.
- A subdomain for the app on the reverse proxy.

## Verification

- `pytest`: streak rules (goal met, leftovers count, repair week, gap resets) and the share photo
  rule (wrong recipe, private photo and revoked token all return 404).
- `docker compose up`, then in a browser at phone width: sign in with a Mealie user, log a cooked
  meal with a photo, add a food entry, add a weight, see totals and streak update.
- Sign in as a second Mealie user, upload a photo for the same recipe, create a share link, open it
  in a private window and see both photos; mark one private and see it disappear; revoke and get 404.
- As the owner, create an invite, open the link in a private window, register, and land signed in;
  confirm the new user exists in Mealie in the chosen household and the link no longer works.
- With a real AI key: ask a nutrition question and get a cited answer; estimate a meal photo;
  attach a photo of a printed recipe, ask to save it, and find it in Mealie with ingredients and
  steps intact; do the same with a link.
- With real Kroger credentials: match a three-item list, add to cart, confirm in the Kroger app.
