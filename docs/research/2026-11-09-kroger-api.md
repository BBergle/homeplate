# Kroger Public API integration reference (researched 2026-11-09)

Labels: **verified (URL)** = read in Kroger's own published content today. **not verified (source)** = taken from a third party or inferred; confirm with a live test.

## 0. How the Kroger pages were read

The developer portal is a Gatsby SPA. Its own content endpoints work without auth:

- `https://developer.kroger.com/api/v1/developer/content/manifests.json` (page tree) and `.../content/search.json` (full body text of all 42 doc pages, public and partner). Found by reading the portal's `app-*.js`. Verified.
- Terms of Service text is embedded in the page chunk `https://developer.kroger.com/component---src-pages-terms-js-9515648f026fcc0b27ef.js` (renders at `https://developer.kroger.com/terms`). Verified.
- FAQ is embedded in `https://developer.kroger.com/component---src-pages-support-faq-js-d7a8e071fb15ee083248.js` (renders at `/support/faq`). Verified.
- NOT obtainable: the OpenAPI reference pages (`/api-products/api/...`). The portal fetches them from `/api/v1/developer/apis`, `/contracts`, `/products`; all return `401 The access_token is missing`. So the Cart API request/response schema was NOT read from Kroger. Chunk hashes in these URLs change on portal redeploys; re-derive from `https://developer.kroger.com/` page source if they 404.
- kroger.com store pages time out or refuse non-browser fetches (see section 9).

Community source used for details Kroger's prose omits: Python client `https://github.com/CupOfOwls/kroger-api` and its `kroger-mcp` (validation constants say "confirmed against live responses", one note "checked live on 2026-10-21"). Treat as strong secondary evidence, not Kroger.

## 1. Registration

- Flow (verified, https://developer.kroger.com/documentation/public/getting-started/quick-start and .../support/website-help/applications): (1) create an account with a short form, verify the emailed link; (2) Manage > Apps > Register; (3) get client ID + client secret.
- The client secret is shown **once** on the Registration Details page; save it immediately (verified, applications page). It can be refreshed later (this invalidates the old one).
- Fields (verified, applications page): Application Name (must not contain "Kroger", must not sound similar or imply endorsement, must be unique in the marketplace); App Description; Support Email; Environment (Production or Certification, one per app, cannot be changed later); API Products (select all you use; scopes are assigned from this choice); optional App Homepage URL, Logo URL, Terms URL, Privacy Policy URL (shown on consent screen); Web Redirect URL(s) (multiple allowed).
- API products to select for this app: **Products, Locations, Cart** (and Identity only if you want `profile.compact`; not needed to add to cart). Community note (not verified, github.com/CupOfOwls/kroger-api README): requesting a scope your app is not registered for makes sign-in fail with `invalid_scope`.
- Self-service: portal says Public APIs are "Available to anyone through self-service registration" (verified, manifests.json). I found no approval step described for Public APIs. Partner APIs need a contract (verified, `/documentation/partner`); not needed here.
- **Cost: not verified.** No Kroger page I read states a price or says "free". Evidence: self-service, no fee mentioned anywhere in docs or ToS; ToS 2d says Kroger may attach "additional terms and/or charges" only for use beyond documented limits. Third-party sites say free (unverified). Treat as "no fee published; confirm at registration".
- Environments (verified, https://developer.kroger.com/documentation/public/getting-started/apis): Production `https://api.kroger.com/v1/`, Certification `https://api-ce.kroger.com/v1/`. Credentials are locked to one environment; register twice for both. **Cart and Identity cannot be tested in certification: no user accounts there** (same page and FAQ). Do cart work in production with a real Kroger account (Kroger suggests a separate test account is fine). CE data "not complete and accurate". A token from one environment fails in the other (FAQ).
- Plan: one production app is enough. Skip CE except for harmless client-credentials smoke tests.
- Credentials rule (ToS 4b): "Developer credentials may not be embedded in open source projects." Keep secret server-side, never in a repo.

## 2. OAuth2

Base: `https://api.kroger.com/v1/connect/oauth2` (verified, auth-tutorial `.env` example).

### 2a. Client credentials (products, locations)

```python
import httpx
r = httpx.post("https://api.kroger.com/v1/connect/oauth2/token",
    auth=(CLIENT_ID, CLIENT_SECRET),               # sends Authorization: Basic base64(id:secret)
    data={"grant_type": "client_credentials", "scope": "product.compact"})
tok = r.json()  # {"expires_in":1800,"access_token":"...","token_type":"bearer"}
```
- Verified (https://developer.kroger.com/documentation/public/security/service-to-service): form-encoded body, Basic header, `scope` param, response has expires_in 1800 and no refresh token.
- Scope `product.compact` for Products (verified FAQ). Locations scope string: **not verified** (docs say locations need a token; the FAQ/spec "AUTHORIZATION" section was not readable). Community lists only `product.compact`, `cart.basic:write`, `profile.compact`. Live test: request with `scope=product.compact` and call `/v1/locations`; if 403 "missing required scopes", ask the registered scope list on the app page.
- Cart scope cannot be used with client_credentials: `{"error":"invalid_scope","error_description":"scope cart.basic:write cannot be used for grant_type client_credentials"}` (verified FAQ).

### 2b. Authorization code (cart)

Authorize (GET, browser redirect), verified https://developer.kroger.com/documentation/public/security/customer:
```
https://api.kroger.com/v1/connect/oauth2/authorize?response_type=code&client_id=ID&redirect_uri=URLENCODED&scope=cart.basic%3Awrite%20product.compact&state=RANDOM&code_challenge=CH&code_challenge_method=S256
```
- Required per docs: `client_id`, `redirect_uri`, `response_type=code`, `scope` (space-separated, URL-encoded). `state` is standard OAuth and used by community client; docs read did not list it (not verified, but include it for CSRF protection).
- Live check today: GET authorize without params returns an HTML "invalid request / Missing parameter client_id" page, confirming the endpoint exists (verified by direct request).
- **PKCE**: documented and recommended for browser/native apps ("Use Authorization Code with PKCE when your application cannot securely store a client secret"), S256, `code_verifier` sent on token request; for confidential clients "continue to authenticate with the authorization header"; PKCE adds, does not replace (verified, customer page). The older tutorial and Postman page show flows with and without PKCE. Conclusion: PKCE is supported; whether it is *enforced* is not verified. Use it anyway plus the Basic header (community client does the same).
- Token exchange (verified, same page):
```python
r = httpx.post("https://api.kroger.com/v1/connect/oauth2/token",
    auth=(CLIENT_ID, CLIENT_SECRET),
    data={"grant_type": "authorization_code", "code": code,
          "redirect_uri": REDIRECT_URI, "code_verifier": verifier})
# {"expires_in":1800,"access_token":"...","token_type":"bearer","refresh_token":"..."}
```
- Refresh (verified, https://developer.kroger.com/documentation/public/security/refresh-token-tutorial):
```python
r = httpx.post(TOKEN_URL, auth=(CLIENT_ID, CLIENT_SECRET),
    data={"grant_type": "refresh_token", "refresh_token": rt})
```
  The customer page's refresh example omits the Basic header while the refresh tutorial includes it; send it (confidential client).
- Lifetimes (verified, FAQ + guides-oauth): access token 1800 s (30 min); refresh token 15,768,000 s (6 months), only issued with auth-code grant, usable only at `/token`. **Single use**: "invalidated once the client has used it to get a new access and refresh token. Any further requests using the refresh token will return a 400 Missing/Invalid Refresh Token" (refresh tutorial). Every refresh returns a new refresh token: store the new one atomically, and serialize refreshes per user (community found concurrent refreshes revoke the sign-in; not Kroger-stated). Sample `expires_in: 172800` in older tutorial JSON conflicts with 1800 elsewhere; trust the field in the live response.
- Token endpoint secret placement: Basic header only (verified). Invalid credentials give `{"error":"unauthorized","error_description":"invalid credentials"}` (FAQ).
- Redirect URI rules: must match a registered URI, else 400 `{"error":"INVALID_REQUEST","error_description":"The redirect_uri did not match the registered redirect_uri for this application"}` (verified troubleshooting + FAQ). Multiple URIs allowed. FAQ example: `https://your-app.com/callback` or `http://localhost:8000/callback` "if you are testing locally"; tutorial uses `http://localhost:3000/callback`. So http on localhost is shown as working. **Not verified**: whether matching is byte-exact (assume yes, incl. trailing slash), whether plain http on a LAN/hostname is accepted, whether https is required for non-localhost production. Plan: register an https URL for the real host and `http://localhost:PORT/callback` for dev.
- Denied consent: redirect with `error=access_denied` appended (verified troubleshooting).
- Consent screen shows your app name/logo; user signs in with their own Kroger account (verified applications page).

## 3. Locations API

`GET https://api.kroger.com/v1/locations` (verified, https://developer.kroger.com/documentation/api-products/public/locations/location-search). Note: Kroger's page text shows `&filter...` straight after `/locations`; that is a typo, use `?`.
```python
httpx.get("https://api.kroger.com/v1/locations",
  params={"filter.zipCode.near": "46802", "filter.radiusInMiles": 15, "filter.limit": 10},
  headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"})
```
- Start point (one of): `filter.zipCode.near`; `filter.latLong.near=lat,lon`; `filter.lat.near` + `filter.lon.near`. Default: 10 results within 10 miles. Without a start point, all locations returned (filterable by chain/department/locationId). No city/state search (FAQ).
- Other filters (verified): `filter.radiusInMiles`, `filter.limit` (max 9999 per doc; community says 1-200 enforced, radius 1-100: not verified), `filter.chain` (e.g. KROGER), `filter.department` (comma list of departmentId), `filter.locationId`.
- **Pickup filter**: no explicit pickup parameter. Use `filter.department=94`; sample response lists department `{"departmentId":"94","name":"Pickup"}` and `{"departmentId":"69","name":"Online Deli/Bakery Ordering"}` (verified sample). Confirm ids via `GET /v1/departments` live. Presence of dept 94 is the best available pickup indicator; the Products `fulfillment.curbside` flag is the per-item truth.
- Response fields (verified sample): `data[].locationId` (8 chars, e.g. "01400413"), `chain` ("KROGER", also "SHELL COMPANY" fuel stations: filter out), `name` ("Kroger - Loveland"), `address{addressLine1,city,state,zipCode,county}`, `geolocation{latitude,longitude,latLng}`, `hours{timezone,open24,monday..sunday{open,close,open24}}`, `phone`, `departments[]{departmentId,name,hours?,phone?}`; `meta`.
- No pagination on this API. Rate limit 1,600 calls/day per endpoint (3 endpoints: locations, chains, departments).
- Also: `GET /v1/locations/{id}`, `/v1/chains` (gives `domain` for building product page URLs), `/v1/departments`.
- Display rule: show names/addresses exactly as returned (acceptable-use). Do not store the user's location (see terms).

## 4. Products API

`GET https://api.kroger.com/v1/products` (verified, .../products/overview and .../products/product-search). Needs `product.compact`.
```python
httpx.get("https://api.kroger.com/v1/products",
  params={"filter.term": "whole milk", "filter.locationId": "01400441",
          "filter.fulfillment": "csp", "filter.limit": 10, "filter.start": 0},
  headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"})
```
- Params (verified): `filter.term` (fuzzy), `filter.productId` (exact; comma list lets you batch), `filter.brand`, `filter.locationId`, `filter.fulfillment`, `filter.limit`, `filter.start`. `GET /v1/products/{id}?filter.locationId=...` for details.
- Fulfillment codes: docs show `csp` (curbside pickup) and `sth` (ship to home). Full list `ais`, `csp`, `dth`, `sth`, case-sensitive, unknown values silently ignored (community, not verified).
- Constraints (community, not verified): term min 3 chars and max 8 words; limit 1-50 (default 10 verified); start 0-250; `filter.brand` alone is rejected: a term or productId is required (also verified by Kroger FAQ: "requires either filter.term or filter.productId"). locationId must be 8 chars (verified error sample `PRODUCT-2011-400`).
- Paging: `meta.pagination{start,limit,total}` (verified). Results from term search are fuzzy and order can change between identical requests (verified overview + FAQ; relevance is popularity-based).
- Response fields (verified, products tutorial): `productId`, `upc` (13 digits with leading zeros, equals productId in samples), `brand`, `description`, `categories[]`, `productPageURI` (prepend chain domain; verified), `aisleLocations[]` (with locationId; sub-fields such as number/shelfNumber referenced in knowledge-check answers, verified), `images[]{perspective,featured,sizes[]{size,url}}` (sizes: thumbnail, small, medium, large, xlarge), `temperature`, `itemInformation{depth,height,width}`, and `items[]{itemId, inventory{stockLevel}, favorite, fulfillment{curbside,delivery,instore,shiptohome}, price{regular,promo}, nationalPrice, size, soldBy}`.
- Price: only returned with `filter.locationId` ("To return the price... must include filter.locationId", FAQ). `price.regular` and `price.promo` (promo is `0` in samples when none). `nationalPrice` also returned; seasonal items only return price when available. **Without a locationId: no price/aisle/fulfillment/stock** (FAQ). **Item not sold at that store: not verified** (docs say with a locationId "the response includes all products sold at that location"; expect absent or priceless item; confirm live and treat "no `price`" as unavailable).
- Stock: `inventory.stockLevel` is HIGH, LOW or TEMPORARILY_OUT_OF_STOCK, omitted when unavailable. `fulfillment.instore` means "sold at the store", not in stock; real inventory confirmed only at Kroger checkout (verified). Aisle presence does not mean in stock (FAQ). Kroger warns API results may differ from kroger.com.
- Rate limit 10,000/day for `/products`.
- No nutrition data (FAQ).

## 5. Cart API

Official (verified, https://developer.kroger.com/documentation/api-products/public/cart/overview): "allows you to add an item to an authenticated customer's cart"; one operation, **Add to cart, method PUT**; 5,000 calls/day. Requires auth-code token with scope `cart.basic:write` (FAQ). Tutorial sample used `cart.basic:rw`; FAQ and community use `cart.basic:write`; use `:write`.

The path and body below are **not verified against Kroger's OpenAPI** (page unreadable); source is the maintained community client, https://github.com/CupOfOwls/kroger-api (`kroger_api/api/cart.py`, `validation.py`):
```python
r = httpx.put("https://api.kroger.com/v1/cart/add",
    headers={"Authorization": f"Bearer {user_token}", "Content-Type": "application/json",
             "Accept": "application/json"},
    json={"items": [{"upc": "0001111041600", "quantity": 2, "modality": "PICKUP"}]})
# success: 2xx, no body to parse (client deliberately ignores the body); a 204 is reported by community
```
- Item fields: `upc` (13-digit string, use the products `upc`), `quantity` (int >= 1), `modality` optional: `PICKUP` or `DELIVERY`. The partner Carts tutorial (verified, different API `/v1/carts`) also uses `"upc"` and `"modality":"PICKUP"`; partner is not available to you.
- Cannot read or remove: confirmed by Kroger FAQ "Why can't I see what I put in the cart?": only add is available; "add the item again to increase the quantity or pass a negative number to reduce the quantity" (FAQ claim; negative quantity behaviour not verified, community validator rejects it); to show the cart you must store product info temporarily and delete it when the customer finishes; checkout means redirecting to www.kroger.com or www.kroger.com/checkout. Partner API needed for read/remove (community README; partner docs exist at `/documentation/api-products/partner/carts/overview`).
- Errors (verified generic): 401 `invalid_token` (expired), 403 `{"errors":{"code":"Forbidden","reason":"missing required scopes"}}`, 400 bad body/param, 429 daily limit, 5xx. Cart-specific error bodies not verified. A timeout or 5xx may still have added the items: do not auto-retry blindly (community `outcome_unknown` guidance); re-adding increases quantity.
- Does it show in the Kroger app immediately: not verified (no source found either way). Test live.
- Kroger requires "always make it clear to users which cart they're adding items to" (branding page).

## 6. Rate limits and throttling (verified, https://developer.kroger.com/support/faq and .../getting-started/apis)

| API | Limit |
|---|---|
| Products | 10,000/day |
| Cart | 5,000/day |
| Locations | 1,600/day per endpoint |
| Identity | 5,000/day |
Per endpoint, not per client or per operation; "applied equally across all clients"; reset 24 hours after the first call to that endpoint. HTTP **429** means daily limit reached (FAQ). No per-second limit is documented. Mitigate: batch with comma-separated `filter.productId`; cache the store picker only if allowed (see terms); one search per list item is fine at household scale (about 30 items/week).

## 7. Terms (all verified)

Sources: ToS https://developer.kroger.com/terms (last modified April 9th, 2019); Acceptable Use https://developer.kroger.com/documentation/public/getting-started/acceptable-use; Branding https://developer.kroger.com/documentation/public/getting-started/branding (updated April 28, 2021). FAQ says all three are "required usage guidelines". ToS 2: Kroger may change terms (30 days notice, immediate for legal/new function) and monitors usage and may suspend without notice (3a).

**(a) Storing / caching API data.**
- ToS 5e: you will not "Scrape, build databases, or otherwise create permanent copies of such content, or keep cached copies longer than permitted by the cache header".
- Acceptable Use, Cart API: "Temporarily storing or caching data for displaying items added to a cart. All data should be terminated when a user closes the application, site, or browser."
- Acceptable Use, Products/Locations prohibit "Systematically scraping or gathering response data to create a database."
- FAQ: customer data "should always be deleted from your application when the customer is finished shopping."
- Do: honor `Cache-Control` headers on responses (not examined; check live); keep search results/prices only for the active session; store only OAuth tokens and the chosen store id. Don't: keep a price history, product catalog, or "what we bought" history; don't persist cart contents after the session.

**(b) "Tracking, sharing, or storing data derived from" cart items or searches.**
- Cart: "Prohibited: Tracking, sharing, or storing data derived from items added to a customer's cart."
- Products: "Prohibited: Tracking, sharing, or storing data derived from customer searches or frequently viewed products."
- Locations: "Prohibited: Tracking, sharing, or storing data about the location of a customer."
- Identity: "Prohibited: Using the profile ID to map or store data associated with a customer."
- Do: treat the shopping list as the user's own data that you may keep (it is not API data); keep search queries ephemeral. Don't: log queries, store "favorite products", per-user purchase stats, saved product matches/UPC mappings per list item, or the user's ZIP/coordinates beyond the session. Storing only a chosen `locationId` per user is a gray area; safest is to ask each session or keep it in the user's browser. Mapping "milk" to a UPC permanently is a derived-data store: avoid.
- Note that this makes kroger-mcp style "local cart tracking" off-limits for persistent storage.

**(c) Sharing API data with third parties (AI model providers).**
- ToS 5e: you may not "Copy, translate, modify, create a derivative work of, sell, lease, lend, convey, distribute, publicly display, or sublicense to any third party" API content, unless expressly permitted by the content owner or law.
- ToS 5c: a user's non-public content may not be exposed to other users or third parties without explicit opt-in consent. ToS 3d: your privacy policy must say what you share with third parties.
- Acceptable Use: "Tracking, sharing... data derived from customer searches" is prohibited; "Manipulating product data in any way" is prohibited.
- Plain reading: sending Kroger product descriptions, prices, UPCs to an LLM provider "conveys" API content to a third party, and an LLM-produced ranking is derived from searches. A careful app should NOT send search results to an AI provider. Safe options: do matching locally (token/fuzzy scoring on description, brand, size; sort by price) and let the person pick; or send the AI only the user's own list text (not Kroger data) to normalize ("2 lbs ground beef" to a clean query). If you really want AI choosing among results, get Kroger's written consent via the developer portal contact form first. This is a judgment, not legal advice; the ToS does not mention AI.

**(d) Price comparison with other retailers.** Acceptable Use, Products: "Prohibited: Comparing products/prices among other retailers." ToS 4a also bars "competitive, comparative or any other type of analysis to develop marketing or business strategies directly or indirectly targeting Kroger customers." Do not show Kroger prices next to other stores' prices, and do not combine this with another grocer's API in the same view.

**(e) Attribution / branding.**
- ToS 6b: display attribution required by the API docs; license to show Kroger Brand Features only to promote that you use the APIs. Branding page: primary banner logos allowed only in the Add-to-Cart use case and only if you do not "directly or indirectly monetize the integration"; the "integration logo" (`https://developer.kroger.com/assets/logos/integrated-blue-text.svg` etc.) may be used to promote use of the APIs but not with text implying partnership.
- ToS 6c / branding: no statement suggesting "partnership with, sponsorship by, or endorsement by Kroger" without prior written approval. App name must not contain "Kroger" or sound similar; app logo must not resemble Kroger's (applications + branding pages).
- Product images must be shown unaltered: no cropping, filters, overlays, text or logos on top (branding). Display product names/descriptions exactly as returned (Acceptable Use).
- Do: name the app e.g. "Pantry Run" (no Kroger), show the integration logo or plain text "Uses Kroger APIs" modestly, use the banner logo only on the Add-to-Cart button. Don't: call it "Kroger helper", crop thumbnails, shorten descriptions, alter prices. Banner name text ("Kroger") in neutral descriptive text such as "Add to your Kroger cart" is in the Add-to-Cart use case; keep it to that button and the store picker (store names are returned data).

**(f) Who the end users may be; personal or non-commercial apps.**
- No clause restricts end users to a number or requires non-commercial use for the public API; ToS 2d says Kroger "sets and enforces limits... (e.g. ... the number of users you may serve), in our sole discretion", and exceeding documented limits needs consent. ToS 1a: you must be of legal age to contract. ToS 2a: require end users to comply with law and the Terms. ToS 9c indemnity applies "if you are a business". Branding: monetization removes logo rights. Terms are from 2019 and modest; nothing found about personal apps specifically.
- End users sign in with their **own** Kroger account via OAuth and only their own cart is touched. Do not let one person's token add to another person's cart, and don't share the developer client secret with friends (ToS 4b: keep confidential; others must use the OAuth flow). Identity API: do not share a profile ID with anyone but that user.
- Under 10 trusted users is within the spirit, but not explicitly sanctioned; if the app ever charges or ads, ask Kroger first.

**(g) Automated adding to cart.** Acceptable Use: "Prohibited: Adding items to a customer's cart without their knowledge. Meaning, you should only add items to a customer's cart that they are explicitly requesting within your experience." Do: add only after the person reviews and presses "Add to my Kroger cart" for the chosen items; show exactly what was sent. Don't: add on a schedule, auto-add suggested or AI-picked substitutes, or add without a confirm step. Also ToS 2c: only access APIs by the documented means; no masking identity (use your own credentials, send a normal User-Agent).

## 8. Practical notes from developers

- Sources: Kroger FAQ (verified) plus https://github.com/CupOfOwls/kroger-api and kroger-mcp READMEs/changelog (community, not verified). I did not locate a Home Assistant integration or blog confirming live behavior within this pass; no source found for cart-appears-in-app latency.
- Works: client-credentials + Products + Locations is straightforward; add-to-cart returns no useful body so success is judged by status code alone.
- Quirks: results for a term vary between calls (verified); API silently ignores bad `filter.fulfillment` values; start range message says 1-250 but accepts 0; long queries (over 8 words) rejected (community); brand-only searches rejected; Kroger's gateway 401 body may be `{"message":"Unauthorized"}` with `WWW-Authenticate` carrying `invalid_token`, so treat any 401 as "refresh and retry once" (community changelog); concurrent refreshes with the same single-use refresh token can invalidate the session (community).
- Prices: reliable only when `filter.locationId` is given; promo `0` means no promo; may not match kroger.com (verified); no guarantee of stock.
- Relevance: store-brand/size variants are many; match on `size` and `brand`; let the person choose rather than auto-pick.

## 9. Fort Wayne, Indiana (partly verified)

- Kroger's own store pages could not be fetched directly (www.kroger.com timed out/refused automation from this environment, 2 tries each). **Not verified from kroger.com content itself.**
- Search engine index of Kroger pages shows kroger.com page titled "Grocery Pickup in Fort Wayne, Indiana" at `https://www.kroger.com/stores/pickup/in/fort-wayne`, and Kroger store-detail URLs `https://www.kroger.com/stores/details/021/00410` (Waynedale, 7008 Bluffton Rd), `/021/00405` (North Clinton, 4120 N Clinton St), `/021/00425`. The search tool summarized the pickup page as listing 8 pickup stores (Chestnut Plaza 10230 Chestnut Plaza Dr; Dupont Village Marketplace 601 E Dupont Rd; Georgetown 6310 E State Blvd; North Clinton; St Joe Center 6002 Saint Joe Center Rd; Village of Coventry 5725 Coventry Ln; Waynedale; West State 1125 W State Blvd), with Southgate Plaza (218 E Pettit Ave) shown without a pickup tag. Kroger Money Services pages (kroger.com domain) confirm Kroger stores at 7008 Bluffton Rd, 218 E Pettit Ave, 10230 Chestnut Plaza Dr, 6002 St Joe Ctr Rd.
- Banner: stores are on kroger.com under the plain **Kroger** banner (division code 021, locationId pattern `021xxxxx`; the Locations API's `chain` is "KROGER", name format "Kroger - <name>"). Inference from the URL domain and API naming; confirm with the live Locations call below.

## 10. What the app must not do (from the terms)

1. Do not add to cart without an explicit per-item (or per-batch) confirmation click by that signed-in person; no auto-add, no schedules, no AI substitutions.
2. Do not send Kroger product, price or search data to an AI provider or any third party; do local matching or send only the user's own list text.
3. Do not persist Kroger-derived data: no product/price/search history, no UPC-per-list-item mappings, no purchase history, no cart contents after the session, no scraped catalog.
4. Do not store user location (ZIP/coordinates) or the Identity profile ID beyond what the session needs; do not share either.
5. Do not compare Kroger prices against any other retailer.
6. Do not alter product names, descriptions, prices, or images (no cropping, overlays, shortened text).
7. Do not put "Kroger" in the app name/logo or imply partnership or endorsement; use primary banner logos only on the Add to Cart button, and only while the app stays non-monetized.
8. Do not share the client secret or one person's tokens; each user signs in with their own Kroger account; keep secret and tokens server-side and out of any public repo.
9. Do not circumvent rate limits (3 users x one list a week is far below them) or mask client identity.
10. Provide a privacy policy describing what you collect and share (ToS 3d) and a way for users to remove their stored tokens (ToS 5d data portability spirit).

## 11. Still unverified and exact live test

Needs: a registered production app (Products, Locations, Cart), your own Kroger account, redirect URI `http://localhost:PORT/callback` registered.

1. Cost and approval: complete registration; note any fee or review prompt.
2. Locations scope: client-credentials token with `scope=product.compact` then `GET /v1/locations?filter.zipCode.near=46802&filter.limit=20`. If 403, retry with scope string shown on the app page.
3. Fort Wayne and banner: from that response confirm `chain`, `name`, and that pickup stores include department `94`; compare with `GET /v1/departments`.
4. Products: `GET /v1/products?filter.term=milk&filter.locationId=<id>` and the same without `filter.locationId`; record price/promo/`nationalPrice`/`fulfillment`/`stockLevel` shape; try a productId for something not sold at that store; check response `Cache-Control` headers (cache lifetime); confirm `filter.start`/`limit` max.
5. Auth code flow: authorize URL with PKCE and `state`; try with and without `code_challenge` to see whether PKCE is enforced; check exact redirect URI matching (trailing slash, 127.0.0.1 vs localhost, plain http on a non-localhost host, https requirement).
6. Refresh: refresh once, confirm new refresh token returned and old one gives 400; confirm lifetimes in the response.
7. Cart: `PUT /v1/cart/add` with `{"items":[{"upc":"...","quantity":1,"modality":"PICKUP"}]}`; record status (200/201/204), body, whether `modality` is optional, error bodies for bad UPC, quantity 0, no scope; whether the item shows in the Kroger app/website cart and how fast; whether adding the same UPC again increments; whether a negative quantity works (FAQ claims it does).
8. 429 body and headers (any `Retry-After`); not worth triggering deliberately.
9. Re-read ToS and Acceptable Use on registration day; they could differ from the 2019/2021 versions seen here, and the OpenAPI reference pages (not readable here) are the authority for the cart schema, scope names and Locations scopes.
