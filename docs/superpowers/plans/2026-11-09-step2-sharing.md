# Homeplate Step 2 (Sharing and Invites) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** iPhone photos upload reliably; every recipe has a gallery of everyone's photos; a recipe can be shared by a public link that needs no account; the owner can invite people, which creates their Mealie account.

**Architecture:** Three new routers (`gallery`, `share`, `invite`) on the existing FastAPI app. Public share links reuse Mealie's own recipe share tokens (created with the sharer's session, read without auth), so no service account is needed. Invites use Mealie's invitation tokens and registration endpoint.

**Tech Stack:** As step 1, plus `pillow-heif` for HEIC photos.

**Spec:** `docs/superpowers/specs/2026-11-09-homeplate-design.md`, build step 2. Where this plan differs from the spec (share tokens instead of `MEALIE_API_TOKEN`), the spec has been updated in the same commit.

## Global Constraints

- No JS build step, no ORM, no inline `<script>`. The only new dependency is `pillow-heif`.
- Public routes (no session): `/login`, `/healthz`, `/static/*`, `/s/*`, `/join/*`. Every other route requires a session.
- All state changes are POST. All SQL is parameterised.
- A user can only change their own entries, photos and weights. Other users' photos are readable only when `private = 0`.
- Public pages show nothing about any user: no names, no diary, no weights, no counts.
- Public pages send `X-Robots-Tag: noindex` and `Referrer-Policy: no-referrer`, and include `<meta name="robots" content="noindex">`.
- Passwords and tokens are never logged, rendered or echoed back into a form.
- Mealie API (verified against the local v3.30.0 spec):
  - `POST /api/shared/recipes` `{"recipeId", "expiresAt"}` (auth) returns `{"id", ...}`; `DELETE /api/shared/recipes/{id}` (auth); `GET /api/recipes/shared/{id}` (no auth) returns the recipe.
  - `GET /api/media/recipes/{recipe_id}/images/min-original.webp` (no auth).
  - `POST /api/households/invitations` `{"uses": 1, "householdId"?}` (auth) returns `{"token", ...}`.
  - `POST /api/admin/households` `{"name"}` (admin) returns `{"id", ...}`.
  - `POST /api/users/register` `{"groupToken", "email", "username", "fullName", "password", "passwordConfirm"}` returns 201.
  - `GET /api/users/self` includes `admin`, `canInvite`, `groupSlug`.
- Recipe fields used on pages: `id`, `slug`, `name`, `description`, `recipeServings`, `totalTime`, `recipeIngredient[].display` and `.title`, `recipeInstructions[].text` and `.title`, `nutrition.calories`, `nutrition.proteinContent`.

## Review Focus

1. A share link must never expose a photo of another recipe, a private photo, or anything after revocation: all 404. Tests in Task 3.
2. Joining with a used or invalid invite, a short or mismatched password, or a taken username: a message, no account, no session, password not echoed. Tests in Task 4.
3. Mealie down while a public page loads: a plain error page, no stack trace. Tests in Tasks 3 and 4.
4. An iPhone HEIC photo uploads and is stored as JPEG; a text file renamed `.heic` is rejected with the normal message. Tests in Task 1.
5. A user who is neither admin nor allowed to invite cannot create an invite, and a non-admin cannot create a household. Tests in Task 4.

---

### Task 1: iPhone photos and same-origin check

**Files:**
- Modify: `requirements.txt`, `app/photos.py`, `app/main.py`, `tests/test_today.py`, `tests/test_auth.py`

**Interfaces:**
- Produces: `photos.save` accepts HEIC/HEIF and MPO input and still writes JPEG. `main.SameOrigin` middleware: any request whose method is not GET, HEAD or OPTIONS and that carries an `Origin` header whose host (and port) differs from the `Host` header gets 403 "Cross-site request blocked".

- [ ] **Step 1:** Tests: `test_heic_upload_becomes_jpeg` (build HEIC bytes with `Image.new("RGB", (64, 48)).save(buf, format="HEIF")` after registering the opener; upload; the stored file's `Image.open(...).format == "JPEG"`); `test_fake_heic_rejected` (`b"not an image"` named `x.heic` shows "That file isn't an image", nothing on disk); `test_cross_origin_post_blocked` (POST `/weight` with `Origin: https://evil.example` is 403 and no row is written); `test_same_origin_post_allowed` (`Origin` equal to the test client's host passes); `test_post_without_origin_allowed`.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Add `pillow-heif` to `requirements.txt`; in `photos.py` call `pillow_heif.register_heif_opener()` at import and use `formats=["JPEG", "PNG", "WEBP", "HEIF", "MPO"]`. Add `SameOrigin` as a pure ASGI middleware next to `BodyLimit`.
- [ ] **Step 4:** `pytest -q` passes; `docker build -t homeplate .` succeeds and `docker run --rm homeplate python -c "import pillow_heif"` exits 0. Commit.

### Task 2: Recipe gallery and photo visibility

**Files:**
- Create: `app/gallery.py`, `app/templates/gallery.html`, `app/templates/notfound.html`, `tests/test_gallery.py`
- Modify: `app/main.py`, `app/today.py` (photo route), `app/me.py`, `app/templates/_entry.html`, `app/templates/me.html`, `app/static/app.css`

**Interfaces:**
- Consumes: `auth.current_user`, `mealie.recipe`, `mealie.me`, `mealie.MealieNotFound`.
- Produces:
  - `GET /r/{recipe_id}`: recipe name, "Open in Mealie" link to `{MEALIE_PUBLIC_URL}/g/{groupSlug}/r/{slug}`, and a grid of photos where `recipe_id` matches and (`private = 0` or the photo is the viewer's), newest first. The viewer's own photos each carry a toggle button and a "Private" label when private. Unknown recipe renders `notfound.html` with 404.
  - `POST /photos/{id}/private`: flips `private` for the owner and redirects 303 to `/r/{recipe_id}`; 404 for anyone else.
  - `GET /photos/{id}` now serves the owner, or any signed-in user when `private = 0`.
  - Today entry rows link the recipe name to `/r/{recipe_id}`. Me gains "Recipes you've cooked": the user's distinct recipes with a count, most recent first, each linking to its gallery.
  - `gallery.html` has `{% block share %}{% endblock %}` below the heading for Task 3.

- [ ] **Step 1:** Write `tests/test_gallery.py`: `test_gallery_shows_everyones_public_photos` (u1 and u2 each upload for recipe `uuid-1`; u1's gallery has both image URLs and both fetch 200); `test_private_photo_hidden_from_others` (u2 uploads with `show_photo` unticked; u1's gallery omits it and `GET /photos/{id}` as u1 is 404; u2 sees it labelled "Private"); `test_toggle_private` (owner toggles and the gallery for the other user changes; a non-owner toggle is 404 and changes nothing); `test_unknown_recipe_404`; `test_me_lists_cooked_recipes` (two entries for one recipe show one row with "2").
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest -q` passes. Commit.

### Task 3: Public share links

**Files:**
- Create: `app/share.py`, `app/templates/public.html`, `app/templates/share.html`, `tests/test_share.py`
- Modify: `app/db.py`, `app/mealie.py`, `app/main.py`, `app/templates/gallery.html`, `app/static/app.css`, `tests/test_auth.py` (route walk exempts `/s/` and `/join/`), `README.md`, `docker-compose.yml` (no `MEALIE_API_TOKEN`)

**Interfaces:**
- Consumes: Task 2's gallery page and photo rows.
- Produces:
  - Table `shares(token TEXT PRIMARY KEY, recipe_id TEXT NOT NULL UNIQUE, created_by TEXT NOT NULL, created_at TEXT NOT NULL)`; `token` is Mealie's share token id.
  - `mealie.create_share(token: str, recipe_id: str) -> str` (expiry ten years out), `mealie.delete_share(token: str, share_id: str) -> None` (a 404 is ignored), `mealie.shared_recipe(share_id: str) -> dict`, `mealie.recipe_image(recipe_id: str) -> bytes | None` (None on 404).
  - `POST /r/{recipe_id}/share` (session): returns the existing row for that recipe or creates one; redirects 303 to `/r/{recipe_id}`. `POST /r/{recipe_id}/unshare` (session): deletes the Mealie token and the row; redirects 303.
  - The gallery's share block shows `{BASE_URL}/s/{token}` as a link plus a "Stop sharing" button, or a "Create share link" button.
  - `GET /s/{token}` (public): `share.html` extending `public.html` (no tab bar, no nav) with recipe name, description, image, servings and time when present, ingredients, steps, calories and protein when present, then the photo grid of that recipe's non-private photos.
  - `GET /s/{token}/photo/{photo_id}` (public): the JPEG only when the photo's `recipe_id` equals the share's and `private = 0`.
  - `GET /s/{token}/image` (public): the recipe's Mealie image proxied through the internal URL; 404 when there is none.
  - An unknown token, or one Mealie no longer recognises, renders a 404 page. Public responses carry the headers in Global Constraints.

- [ ] **Step 1:** Write `tests/test_share.py`: `test_share_page_needs_no_session` (a fresh client with no cookie gets 200 with the recipe name, an ingredient, a step and both users' public photo URLs); `test_share_page_names_no_user` (no user's `fullName` or username appears); `test_private_photo_not_on_share` (not in the page; its `/s/{token}/photo/{id}` is 404); `test_photo_of_other_recipe_404`; `test_unshare_makes_everything_404` (page, photo and image); `test_share_is_reused` (two POSTs give one row and one Mealie call); `test_share_headers` (`X-Robots-Tag` and `Referrer-Policy`); `test_share_mealie_down` (502, contains "Can't reach Mealie", no "Traceback"); `test_share_requires_session_to_create`.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement. Ingredient rows with a `title` render it as a subheading above the ingredient; step text renders as plain text with line breaks preserved.
- [ ] **Step 4:** `pytest -q` passes. Commit.

### Task 4: Invites and joining

**Files:**
- Create: `app/invite.py`, `app/templates/invite.html`, `app/templates/join.html`, `tests/test_invite.py`
- Modify: `app/mealie.py`, `app/auth.py`, `app/main.py`, `app/templates/me.html`

**Interfaces:**
- Produces:
  - `mealie.MealieRejected(MealieError)` raised by the request helper for 400, 403, 409 and 422.
  - `mealie.create_household(token: str, name: str) -> str`, `mealie.create_invite(token: str, household_id: str | None) -> str`, `mealie.register(invite: str, full_name: str, email: str, username: str, password: str) -> None`.
  - `auth.start_session(user: dict, token: str) -> Response`: the session-creation half of the existing login route, reused by join.
  - `GET /invite` (session): calls `mealie.me`. Admins and users with `canInvite` see a form: "My household" (default) and, for admins only, "Their own household" with a name field. Others see "Ask the person who runs this server to invite people." with status 403.
  - `POST /invite` (session): same permission check; creates the household when asked (admin only, name 1 to 50 characters), creates a single-use invite, and renders `{BASE_URL}/join/{token}` as a link.
  - `GET /join/{token}` (public): form with name, email, username, password, confirm password; correct `autocomplete` values (`name`, `email`, `username`, `new-password`).
  - `POST /join/{token}` (public): password at least 8 characters and equal to its confirmation, otherwise re-render with a message; `mealie.register`; on `MealieRejected` re-render with "Couldn't create the account. The invite may have been used, or the username or email is taken."; on success sign in via `mealie.login` and `auth.start_session`, redirect 303 to `/`. Name, email and username are kept in the re-rendered form; the password fields are always empty.
  - Me gains an "Invite someone" link to `/invite`.

- [ ] **Step 1:** Write `tests/test_invite.py`: `test_admin_invites_to_own_household` (one invitation call with no `householdId`; the page shows a `/join/` link); `test_admin_invites_to_new_household` (household created with the posted name, its id passed to the invitation); `test_can_invite_user_sees_no_household_option` (and a posted new-household request from them is refused with 403, no Mealie household call); `test_plain_user_cannot_invite` (GET and POST both 403, no Mealie calls beyond `users/self`); `test_join_creates_account_and_signs_in` (register called with the token and fields, then `/` loads as the new user); `test_join_password_rules` (short and mismatched: message, no Mealie call); `test_join_rejected_by_mealie` (message, no session cookie, response does not contain the password, username is kept); `test_join_mealie_down` (502 page, no "Traceback"); `test_join_is_public` (no cookie needed for GET).
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest -q` passes. Commit.
- [ ] **Step 5:** Smoke test against the real Mealie in `docker compose` (rebuild first). With curl and cookie jars, record commands and key output in the report:
  - Sign in as the default admin; create a recipe with one ingredient and one step; log a cooked entry with a JPEG and another with a generated HEIC.
  - Open `/r/{id}`; create a share link; fetch `/s/{token}`, a photo and `/s/{token}/image` with no cookies; confirm headers; stop sharing and confirm 404s. Confirm Mealie accepted the ten-year expiry.
  - Create an invite to a new household; join with it as a new user (Mealie runs with `ALLOW_SIGNUP=false`, which must not block an invited registration); confirm the redirect to `/`, that the user exists in Mealie in the new household (admin API), and that reusing the link fails with the message.
  - Any difference between the mocked and real Mealie responses is fixed in `app/mealie.py` with a test adjusted to the real shape, and stated in the report.
