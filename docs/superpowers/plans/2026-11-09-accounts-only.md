# Homeplate Accounts-Only Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nothing about any recipe or user is visible without an account. Public share pages are removed; a share link is a plain link to the recipe page inside the app. An admin can switch on account requests, which adds "Create account" to the login screen; each request waits for an admin's approval.

**Architecture:** Delete the public share router and stop using Mealie share tokens. The signed-in recipe page (`/r/{id}`) takes over the full recipe layout. A small `access` router adds an instance-wide sign-up switch, a public request form, a private status page per request, and an admin page that approves a request by creating a single-use Mealie invite, handing off to the existing `/join/{token}` flow.

**Tech Stack:** Unchanged.

**Spec:** `docs/superpowers/specs/2026-11-09-access.md`. It replaces the public share page in the original design.

## Global Constraints

- Public routes (no session) after this plan: `/login`, `/healthz`, `/static/*`, `/join/*`, `/request`, `/request/*`. Nothing under `/s/` exists. Every other route requires a session.
- No public response contains a recipe's name, text or image, any photo, or anything about any user.
- Public pages under `/join/` and `/request` send the existing headers: `X-Robots-Tag: noindex`, `Referrer-Policy: same-origin` (never `no-referrer`: browsers then send `Origin: null` on the form post and the same-origin guard rejects it), and the existing Content-Security-Policy.
- Account requests never store a password. Request fields: name (1 to 100 characters), email (contains "@", at most 254), note (optional, at most 200).
- The sign-up switch is off by default. Only a Mealie admin (checked live with `mealie.me` on every admin request) can change it or decide a request.
- At most 20 pending requests exist at once and at most one pending request per email; the public form answers the same way whether or not a limit was hit.
- A request's status page is addressed by a 32-byte random secret and shows only that request's state.
- All state changes are POST; all SQL is parameterised; no new dependency; no inline `<script>` or `style=""`; styling uses the existing tokens and components.
- Photo privacy is unchanged: a private photo is visible only to its owner; other signed-in users see non-private photos of a recipe.
- The login `next` parameter is honoured only when it matches `^/r/[A-Za-z0-9-]{1,64}$`; anything else goes to `/`.

## Review Focus

1. Every former public address (`/s/{token}`, `/s/{token}/photo/{id}`, `/s/{token}/image`) returns 404 or the login redirect, signed in or not, and no route serves a photo or recipe image without a session. Tests in Task 1.
2. With the switch off, `/request` (GET and POST) is 404 and the login page has no "Create account"; turning it off does not delete pending requests but they can no longer be created. Tests in Task 2.
3. A non-admin cannot read the admin page, flip the switch, or approve or decline, by GET or POST. Tests in Task 2.
4. Approving twice, approving a declined request, or approving when Mealie fails leaves one consistent state and at most one invite. Tests in Task 2.
5. The request form submits from a real browser (not only curl) with the same-origin guard on. Checked in Task 2's smoke test.

---

### Task 1: Remove public sharing; full recipe page for members

**Files:**
- Delete: `app/share.py`, `app/templates/share.html`, `app/templates/public_gone.html`, `tests/test_share.py`
- Create: `app/templates/recipe.html`, `tests/test_recipe.py`
- Modify: `app/gallery.py`, `app/mealie.py` (remove `create_share`, `delete_share`, `shared_recipe`; keep `recipe_image`), `app/db.py` (stop creating `shares`; `DROP TABLE IF EXISTS shares`), `app/main.py` (router and public prefixes), `app/auth.py` (login `next`), `app/templates/gallery.html` (replaced by `recipe.html`), `app/templates/today.html` (photo hint wording), `app/static/app.css`, `tests/test_gallery.py`, `tests/test_auth.py`, `tests/test_ui.py`, `tests/test_stats.py`, `README.md`, the spec

**Interfaces:**
- Produces:
  - `GET /r/{recipe_id}` (session): the recipe's Mealie image when it has one (from `GET /r/{recipe_id}/image`), name, time and servings chips, description, ingredients, method, then the photo grid (non-private photos plus the viewer's own, with the existing Private chip and toggle on the viewer's own), a "Link to this recipe" card holding `{BASE_URL}/r/{id}` in a read-only field with the line "Only people with an account can open this.", and "Open in Mealie". Unknown recipe is the existing 404 page.
  - `GET /r/{recipe_id}/image` (session): the Mealie image proxied through `mealie.recipe_image`; 404 when there is none.
  - `POST /r/{id}/share` and `/unshare` no longer exist.
  - `GET /login?next=/r/<id>` renders the form with `next` carried in a hidden field; after a successful sign-in the redirect goes there when it passes the pattern in Global Constraints. An unauthenticated request for `/r/<id>` redirects to `/login?next=/r/<id>`.
  - The photo checkbox hint on Today reads "Show this photo to others on the recipe page".

- [ ] **Step 1:** Write `tests/test_recipe.py`: `test_recipe_page_shows_recipe_and_photos` (name, an ingredient, a step, both users' non-private photos); `test_private_photo_only_for_owner`; `test_recipe_image_requires_session` (200 signed in, redirect to login without a cookie); `test_old_public_addresses_gone` (`/s/x`, `/s/x/photo/1`, `/s/x/image` are 404 or a login redirect, with and without a cookie, and never 200); `test_no_share_routes` (POST `/r/{id}/share` is 404 or 405); `test_link_card` (the read-only field holds `{BASE_URL}/r/{id}`); `test_login_next` (sign-in with `next=/r/abc` redirects to `/r/abc`; `next=https://evil.example`, `next=//evil.example`, `next=/me` and `next=/r/../../x` all redirect to `/`); `test_unauthenticated_recipe_redirects_with_next`; `test_route_walk_public_list` (update the route-walk test's public prefixes to the list in Global Constraints).
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement. Move the recipe layout from `share.html` into `recipe.html` extending `base.html`; move the gallery tests that still apply into `tests/test_recipe.py` or keep them in `tests/test_gallery.py` unchanged in what they assert.
- [ ] **Step 4:** `pytest -q` passes. Commit.

### Task 2: Sign-up switch, account requests, admin page

**Files:**
- Create: `app/access.py`, `app/templates/request.html`, `app/templates/request_status.html`, `app/templates/admin.html`, `tests/test_access.py`
- Modify: `app/db.py` (tables `instance` and `requests`; add `users.is_admin` with a guarded `ALTER TABLE`), `app/auth.py` (store `is_admin` at sign-in; pass `signups_open` to the login template), `app/main.py` (router, public prefixes and headers), `app/me.py` and `app/templates/me.html` (admin link with pending count), `app/templates/login.html`, `app/invite.py` (reuse its household-and-invite creation), `app/static/app.css`, `README.md`

**Interfaces:**
- Consumes: `mealie.me`, `mealie.create_household`, `mealie.create_invite`, `auth.base_url`, the existing `/join/{token}` flow.
- Produces:
  - Tables: `instance(key TEXT PRIMARY KEY, value TEXT NOT NULL)`; `requests(id INTEGER PRIMARY KEY AUTOINCREMENT, secret TEXT NOT NULL UNIQUE, name TEXT NOT NULL, email TEXT NOT NULL, note TEXT, status TEXT NOT NULL CHECK (status IN ('pending','approved','declined')), invite_token TEXT, created_at TEXT NOT NULL, decided_at TEXT, decided_by TEXT)`; `users.is_admin INTEGER NOT NULL DEFAULT 0`.
  - `access.signups_open() -> bool`.
  - `GET /login`: a "Create account" secondary button linking to `/request` only when sign-ups are open.
  - `GET /request` (public): the form, or 404 when sign-ups are closed. `POST /request` (public): validates; on success creates the row and redirects 303 to `/request/{secret}`; when a limit in Global Constraints is hit it redirects to a status page that reads the same as a new pending request (for a duplicate email, the existing request's page is not revealed: show a generic "Request sent" page with no secret).
  - `GET /request/{secret}` (public): pending shows "Request sent. Keep this page: it will change when your request is answered."; approved shows "You're approved" and a primary button to `/join/{invite_token}`; declined shows "This request wasn't approved."; unknown secret is 404.
  - `GET /admin` (session, admin only, otherwise the 403 page): the switch as a form, pending requests (name, email, note, when) each with Approve (household choice: mine, or new with a name) and Decline, and the 20 most recent decided requests with the join link for approved ones.
  - `POST /admin/signups` (`open` = `1` or `0`), `POST /admin/requests/{id}/approve` (`where`, `household_name`), `POST /admin/requests/{id}/decline`: admin only; each redirects 303 to `/admin`. Approve creates the household when asked, then the invite, then stores it; it is a no-op on a request that is not pending.
  - Me: for users whose stored `is_admin` is 1, an "Admin" secondary button showing the pending count ("Admin · 2 requests").

- [ ] **Step 1:** Write `tests/test_access.py`: `test_closed_by_default` (login has no "Create account"; GET and POST `/request` are 404); `test_admin_opens_signups` (then the login page has the button and `/request` is 200); `test_request_flow` (POST creates one pending row, redirects to its status page, which says "Request sent"; no password field exists on the form); `test_request_validation` (blank name, email without "@", over-long fields: message, no row); `test_request_limits` (a second pending request for the same email creates no second row and the response looks like success; with 20 pending, the 21st creates no row and looks like success); `test_status_page_states` (pending, approved with the `/join/` link, declined, unknown secret 404); `test_non_admin_blocked` (GET `/admin` and each admin POST are 403 for a plain user and for a `canInvite` user, with no Mealie calls beyond `users/self` and no state change); `test_approve_creates_one_invite` (one invite call; row approved with the token; a second approve makes no Mealie call); `test_approve_new_household` (household created with the posted name and its id passed to the invite); `test_approve_mealie_down` (request stays pending, no token stored, the admin sees "Can't reach Mealie"); `test_decline` (row declined; approving it afterwards is a no-op); `test_closing_keeps_pending` (rows remain, form is 404); `test_public_headers_on_request` (`Referrer-Policy: same-origin`, noindex, CSP on GET and POST); `test_me_admin_link` (admin sees "Admin · 1 request"; a plain user sees no admin link); `test_is_admin_migration` (a database created without the column gains it on connect).
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest -q` passes. Commit.
- [ ] **Step 5:** Smoke test against the real Mealie in `docker compose` (rebuild first), recording commands and key output with secrets redacted: as admin turn sign-ups on; in headless Chrome (a real browser, as the join form was verified before) submit the request form and reach the status page; as admin approve it into a new household; reload the status page, follow the join link, create the account and land signed in; confirm the user exists in that household in Mealie; turn sign-ups off and confirm `/request` is 404 and the login page has no button; confirm `/s/anything` is not served. Screenshot login (switch on), the request form, the status page and the admin page at 375 and 390px in light and dark with the helper, and look at them.
