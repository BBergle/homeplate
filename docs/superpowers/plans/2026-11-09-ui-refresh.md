# Homeplate UI Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle every page to the researched design: a calm, phone-first "kitchen notebook" look with a calorie ring, a shorter logging form, one icon tab bar, badge achievements and a good-looking public recipe page.

**Architecture:** Presentation only. One rewritten stylesheet built on design tokens, restructured Jinja templates, inline SVG icons from one macro file, and a few extra values computed in the existing page functions. No route, schema or behaviour changes except where a task says so.

**Tech Stack:** Unchanged (Jinja2, htmx, one CSS file, inline SVG).

**Spec:** `docs/superpowers/specs/2026-11-09-ui-design.md` (the research-backed design spec: tokens, component specs, screen-by-screen changes). Where this plan and the spec differ, this plan wins; the differences are listed under Global Constraints.

## Global Constraints

- No JS build step, no CSS framework, no web fonts, no chart library, no new dependency. One stylesheet: `app/static/app.css`.
- No inline `<script>` and no `style=""` attributes in any template (a test enforces both). SVG presentation attributes are fine.
- Colours, spacing, radii and type sizes come only from the spec's design tokens (CSS custom properties); dark mode via `@media (prefers-color-scheme: dark)` token overrides.
- Calorie and protein numbers never use the danger or warning colour. Over target reads "N over" in the normal colour.
- Every interactive target is at least 44px; inputs are at least 16px font size; no horizontal scroll at 375px; visible `:focus-visible` outline; `prefers-reduced-motion` respected.
- State is never shown by colour alone (active tab, earned/locked, messages).
- Icons are inline SVG from `app/templates/_icons.html` macros (24px, `stroke="currentColor"`, `aria-hidden="true"`). No emoji as icons.
- Routes, form field names, validation rules, messages and access rules do not change. Existing tests keep their behavioural assertions; a string assertion may change only when this plan changes that string.
- Differences from the spec: the gallery and public page show no names, dates or "cooked N times" counts for anyone; the join page does not say who invited you; the public page keeps `noindex`; cross-document view transitions are not used; deleting an entry stays a plain POST behind a `<details>` disclosure (no `<dialog>`).
- Public pages (`/s/*`, `/join/*`) additionally send `Content-Security-Policy: default-src 'self'; img-src 'self'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'`.

## Review Focus

1. A long recipe name, a 5-digit calorie value, or a long unbroken word in a description must not cause horizontal scroll at 375px. Test in Task 2 (markup classes) and checked in screenshots.
2. No calorie target set: the Today hero shows plain totals with no ring and no "left/over" text. Test in Task 2.
3. Over target: ring full, text "N over", no danger or warning class. Test in Task 2.
4. A user with history but a zero streak sees "Fresh start this week", never "0 weeks"; a brand-new user sees neither a streak nor a failure message. Test in Task 3.
5. Public pages render with no tab bar and no inline script or style, and pass their CSP. Test in Tasks 1 and 4.

---

### Task 1: Foundation (tokens, shell, shared components, small pages)

**Files:**
- Create: `app/templates/_icons.html`, `app/static/icon-180.png`, `tests/test_ui.py`
- Modify: `app/static/app.css` (rewrite), `app/templates/base.html`, `app/templates/public.html`, `app/templates/login.html`, `app/templates/error.html`, `app/templates/soon.html`, `app/templates/notfound.html`, `app/templates/public_gone.html`, `app/templates/public_error.html`, `app/static/manifest.json`, `app/main.py` (CSP on public responses)

**Interfaces:**
- Produces:
  - CSS tokens and component classes exactly as named in the spec: `.card`, `.page-head`, `.btn` with `.btn-primary`, `.btn-secondary`, `.btn-danger`, `.field` (label above input), `.check`, `.msg` with `.msg-error` and `.msg-ok`, `.muted`, `.num` (tabular figures), `.stat` (`.stat-v`, `.stat-l`), `.empty`, `.chip`, `.more` (styled `<details>`), `.tabs`, `.photo-grid`, `.thumb`. Later tasks add page-specific rules under a comment heading per page.
  - `_icons.html` macros: `icon(name)` for `today`, `me`, `order`, `ask`, `plate`, `check`, `lock`, `camera`, `chevron`, `plus`, `more`.
  - `base.html`: head tags from the spec's "Head and PWA changes"; `{% block head %}`; one tab bar of four tabs with icon and label, `aria-current="page"` on the active tab (from `request.url.path`; `/r/*` and `/invite` count as Me, `/` as Today); the second footer bar is removed; safe-area padding.
  - `public.html`: same head (minus manifest and htmx), `{% block head %}`, centred column, footer "Shared from Homeplate".
  - Login: wordmark with plate icon, tagline "Cook at home. Keep the change.", helper "Use your Mealie account.", inputs with `autocomplete="username"` plus `autocapitalize="none"` `autocorrect="off"` `spellcheck="false"`, and `autocomplete="current-password"`; error shown with `.msg-error`.
  - Order and Ask placeholders as empty-state cards: "Grocery ordering is on the way" / "The food assistant is on the way" with one line each.
  - `manifest.json` `background_color` and `theme_color` `#f6f4ef`.

- [ ] **Step 1:** Write `tests/test_ui.py`: `test_no_inline_script_or_style` (every file in `app/templates` has no `<script` without `src` and no `style="`); `test_active_tab` (`/` marks Today, `/me` marks Me, `/order` marks Order with `aria-current="page"`, and exactly one tab is marked); `test_head_tags` (viewport has `viewport-fit=cover`, two `theme-color` metas with `media`, `color-scheme` meta, apple-touch-icon is `icon-180.png` and the file is 180x180); `test_login_autofill` (the attributes above); `test_public_csp` (a `/join/x` response carries the CSP header; `/login` does not); `test_no_second_footer_bar` (no `class="links"` in a signed-in page).
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement. Generate `icon-180.png` once with Pillow from `icon-512.png` (do not commit the command).
- [ ] **Step 4:** `pytest -q` passes (update only string assertions this task changed). Run the screenshot helper named in the dispatch and look at login, Order and the shell in light and dark. Commit.

### Task 2: Today

**Files:**
- Modify: `app/today.py` (`_page` context only), `app/templates/today.html`, `app/templates/_entry.html`, `app/templates/_recipe_results.html`, `app/static/app.css`, `tests/test_today.py`, `tests/test_ui.py`

**Interfaces:**
- Consumes: Task 1 classes and macros; `stats.week_totals`.
- Produces, in page order:
  1. Header "Today" with the local date ("Monday 9 Nov").
  2. Hero card. With a calorie target: an SVG ring (the spec's markup, `pathLength="100"`, percentage capped at 100) with the eaten total in the centre and "N left" or "N over" beneath; without one: the total alone, no ring. Protein: `<progress value max>` with "62 of 100 g protein" when a target is set, else "62 g protein". Below: "Cooked this week" as filled and empty dots (`weekly_goal` dots, extra cooks beyond the goal shown as "+N"), text "2 of 3", linking to `/me`.
  3. "I cooked" card: recipe search and results, the primary "Log meal" button, and a `<details class="more">` "Photo, note and nutrition" holding photo, "Share this photo on the recipe page" (same `show_photo` field), leftovers, note, calories, protein. The details is open when the page re-renders with an error.
  4. Entries as one card with a list: thumbnail or plate placeholder, name, a muted line "Cooked · 420 kcal · 32 g · 6:40 PM" (kind as a `.chip`: Cooked, Leftovers, Added), and a `<details class="more">` containing the Remove button. Empty state per the spec ("Nothing logged yet" plus one sentence).
  5. "Add food" as a `<details class="more">` card (open when its submit errored).
  6. Weight as a compact card with one field and button.
  7. "Kitchen" card with the Mealie links (Recipes, Meal plan, Shopping list), omitted when `MEALIE_PUBLIC_URL` is empty.
  - `_page` adds: `date_label`, `cal_pct` (None without a target), `cal_left`, `cal_over`, `week_count`, `week_extra`, `entry.time_label` (local time from `created_at`).
  - Number inputs: `inputmode="numeric"` with `step="1"` for calories, `inputmode="decimal"` for protein and weight; `enterkeyhint` set; search input `enterkeyhint="search"`.

- [ ] **Step 1:** Tests: `test_hero_no_target` (no `<svg class="ring"`, no "left", no "over"); `test_hero_under_target` (target 2000, eaten 500: ring present with `stroke-dasharray="25 100"`, "1,500 left"); `test_hero_over_target` (eaten 2120: dasharray `100 100`, "120 over", and neither `danger` nor `warning` appears in the hero markup); `test_week_dots` (goal 3 with 2 home meals this week: "2 of 3", two filled dots, one empty; with 5: three filled and "+2"); `test_optional_fields_collapsed` (photo input is inside a `<details>` without `open`; after a validation error on the cooked form it has `open`); `test_remove_is_disclosed` (the delete form sits inside a `<details>`); `test_entry_time_uses_tz`; `test_long_text_classes` (entry name element carries the class the stylesheet gives `overflow-wrap: anywhere`).
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest -q` passes. Screenshot Today (empty, and with two entries, one with a photo, with and without a calorie target) in light and dark and look at them. Commit.

### Task 3: Me and Invite

**Files:**
- Modify: `app/me.py` (`_page` context, `sparkline`), `app/templates/me.html`, `app/templates/invite.html`, `app/static/app.css`, `tests/test_me.py`, `tests/test_ui.py`

**Interfaces:**
- Consumes: Task 1 classes and macros; `stats`.
- Produces, in page order:
  1. Weekly goal hero: large "2 of 3", the same dots as Today, and one line: "Streak 4 weeks" when the streak is 1 or more; "Fresh start this week" when the streak is 0 and the user has at least one earlier home meal; nothing for a brand-new user.
  2. Stat tiles: "$84 saved" with caption "vs ordering delivery" (clamped at $0), and total home meals.
  3. Achievements as a 3-column badge grid: earned is a filled accent circle with a check icon and caption "Earned"; locked is a dashed outline with a lock icon and a caption giving the criterion ("Cook 10 meals", "Cook 50 meals", "Hit your goal 4 weeks running", "Cook 5 different recipes", "Log your first cook").
  4. Weight card: latest value large (one decimal, no trailing ".0"), goal muted, sparkline with a dashed goal line when a goal is set and inside the range, the last point marked, caption "Last 90 days", and a "Log weight" link to `/`.
  5. "Recipes you've cooked" list.
  6. Settings inside a `<details class="more">` (open when a settings error is shown), grouped in fieldsets "Goals" and "Costs"; numbers shown without trailing ".0".
  7. "Invite someone" as a secondary button; Sign out as a danger button, separated.
  - `me.sparkline(points, w=320, h=80, goal=None) -> dict` with keys `line` (points string), `last` (`(x, y)`), `goal_y` (float or None); `{}` for fewer than two points.
  - Invite page restyled with Task 1 form components; the generated link is shown in a read-only field with the link beneath.

- [ ] **Step 1:** Tests: `test_streak_copy` (new user: neither "Streak" nor "Fresh start"; history but streak 0: "Fresh start this week" and no "0 weeks"; streak 2: "Streak 2 weeks"); `test_savings_never_negative` (home cost above delivery cost shows "$0 saved"); `test_badges` (earned badge has "Earned" and the check icon; locked has its criterion text and the lock icon; five badges); `test_numbers_trimmed` (`180.0` renders "180", `180.5` renders "180.5", settings show `25` not `25.0`); `test_sparkline` updated to the dict shape (one point gives `{}`; two give a `line` with two pairs and `last` equal to the final pair; a goal inside the range gives `goal_y` inside the box, outside gives None); `test_settings_open_on_error`.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest -q` passes. Screenshot Me (new user, and with data) and Invite in light and dark and look at them. Commit.

### Task 4: Gallery, public share page, join

**Files:**
- Modify: `app/templates/gallery.html`, `app/templates/share.html`, `app/templates/join.html`, `app/templates/public.html`, `app/share.py` (context only), `app/static/app.css`, `tests/test_share.py`, `tests/test_gallery.py`, `tests/test_invite.py`, `tests/test_ui.py`

**Interfaces:**
- Consumes: Task 1 classes and macros.
- Produces:
  - Gallery: header with the recipe name and photo count ("3 photos"); `.photo-grid` of square, lazy-loaded thumbnails linking to the full image; the viewer's own photos carry a small "Private" chip and the toggle inside a `<details class="more">`; share block as a card (link in a read-only field, "Stop sharing" as a danger button, or "Create share link" as primary); empty state "No photos yet" with its sentence; "Open in Mealie" as a secondary button.
  - Public share page, in order: hero image when the recipe has one (`fetchpriority="high"`, 4:3, cover); title; meta chips (time, "Serves 4"); description; Ingredients card (section titles as subheadings); Method as a numbered list at 1.0625rem/1.6 and at most 65ch; "Photos" grid when there are any; footer. `{% block head %}` gets `og:title`, `og:description` (first 200 characters of the description, when present) and `og:image` (absolute URL of `/s/{token}/image`, only when the recipe has an image).
  - Join: centred card like login with the wordmark, "Create your account", the five fields with their `autocomplete` values and `enterkeyhint`, primary "Join", errors as `.msg-error`.

- [ ] **Step 1:** Tests: `test_share_og_tags` (title always; image only with an image, and absolute); `test_share_order` (ingredients markup precedes method markup, photos last); `test_share_no_app_chrome` (no tab bar, no htmx, no manifest link, no inline script or style); `test_gallery_count_and_private_chip`; `test_join_layout` (wordmark, five inputs with the right `autocomplete`, one primary button); keep every existing access-rule test unchanged.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest -q` passes. With the local stack: create a recipe with an image, ingredients and steps in Mealie, log it twice with photos, share it, create an invite; screenshot the gallery, the share page and the join page in light and dark and look at them. Commit.
