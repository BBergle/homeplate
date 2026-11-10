# The assistant (step 3)

Design for the Ask tab. Written 2026-11-09 from the owner's requests over one long session. Nothing here is built yet.

## What it is for

The owner wants the app to do the thinking that stops them cooking: finding something good to make, getting it into their recipes, turning it into a shopping list, and keeping the calorie diary honest without typing numbers. The assistant is how they ask for those things in their own words.

## Decisions made by the owner

- The assistant can act on the app, not just answer. Example given: "Look for good cinnamon roll recipes" returns a list of recipes, each with an Add button that imports it.
- **The assistant proposes; the owner taps.** It may look things up without asking. Anything that changes something appears as a card with a button, and nothing happens until the button is tapped.
- Filling the Kroger cart stays in code (step 4). The assistant can add items to the shopping list and bring up the send-to-Kroger screen.
- Each person uses their own AI key. Without a key, the Ask tab and the AI buttons are unavailable for that person and everything else works.
- Providers: OpenRouter, Google Gemini and Anthropic Claude.
- It searches the web through the AI provider's own search.
- Reddit: no Reddit API. The assistant searches the web with a Reddit focus, and pasting a link's text or a screenshot always works.
- YouTube: the assistant can search YouTube. If a video's description contains the recipe or a link to it, that is imported, and the video is attached to the recipe as a link.
- Recipe cards show a photo when the recipe has one.
- "What do I have": the owner tells it, or sends a photo of the fridge, and it suggests recipes. No stored pantry inventory.
- It can import a recipe from a photo (cookbook page, recipe card, screenshot), pasted text or a link.
- It can estimate calories from a photo of a meal.
- It can help work out a workout's calories from a description.

## Calls made in design (told to the owner along the way; not each confirmed)

- OpenRouter is built first: one key reaches most models, and its docs say its web search tool works alongside the app's own tools. Claude and Gemini direct keys follow as separate pieces of work, because their compatibility modes drop web search.
- The YouTube search uses Google's official API with one key for the whole server, set by the owner. Without it the assistant falls back to web search for videos.
- One conversation per person is kept on the server so a reload does not lose it. "New chat" clears it. No chat history browser.
- AI keys are stored encrypted, using `SECRET_KEY`. Changing `SECRET_KEY` means re-entering keys.
- A workout described in words is turned into activity, minutes and effort by the model, and the calories come from the app's own formula unless the person gave a number, so the numbers match the manual form.
- Images on result cards are fetched by the server, not by the phone, and only for links that the assistant itself proposed.
- If Mealie cannot import a web page, the card says so and suggests pasting the recipe text. The server does not scrape pages itself.

## Calls settled after a builder read the design (mine, not the owner's)

- **Keys need a real `SECRET_KEY`.** The app refuses to save an AI key while `SECRET_KEY` is unset or still a placeholder (`dev`, `change-me`), and says why. Otherwise stored keys would be readable by anyone with the database file.
- **No key yet:** the Ask tab stays in the tab bar and shows a short "add your key in Settings" page.
- **Default model:** `openai/gpt-5-nano` on OpenRouter (the cheapest found with tools, photos and built-in search). The person can type another model name; the app checks OpenRouter's model list and warns if the model lacks tools or photo input.
- **No spending cap in the app.** Each message is limited to six look-up rounds; web searches are billed per search by the provider, and a spending limit can be set on the key at the provider.
- **Shopping list:** Mealie allows several lists. "Add to list" uses the person's first list and names it on the card.
- **Old cards:** a proposal older than a day shows "Expired, ask again" in place of its button.
- **Meal plan and nutrition proposals** may only refer to recipe ids that a look-up returned in that conversation; anything else is rejected.
- **Result-card images:** fetched only over https, only from public internet addresses (private and local addresses are refused, including after redirects), with a size limit.
- **Photos sent to the model** are shrunk to about 1280 pixels first. The photo itself is not kept in the conversation history.
- **Provider errors** (bad key, out of credit, rate limit) show a plain message and keep any cards already made.
- **Longer waits:** model calls and Mealie's link import get their own, longer time limits than the app's normal 10 seconds.
- **The model is told today's date** in the app's timezone.

## How a turn works

1. The person sends a message, optionally with one photo.
2. The app calls the model with the conversation, the tool list and web search switched on.
3. The model may call **look-up tools**. The app runs them and returns the results. This repeats up to six times per message.
4. The model finishes with text and, when it wants something changed, **proposals**.
5. The app shows the text, the sources it used, and one card per proposal.
6. Tapping a card's button performs that one action in code and marks the card done.

### Look-up tools (run without asking)

| Tool | What it returns |
|---|---|
| `search_my_recipes(query)` | Matching recipes from the person's Mealie library |
| `get_recipe(id)` | One recipe's ingredients, steps and nutrition |
| `suggest_from_foods(foods, max_missing)` | Library recipes that use those foods (Mealie's suggestion feature) |
| `get_meal_plan(start, end)` | Planned meals in a date range |
| `get_shopping_list()` | The current shopping list |
| `get_today()` | Today's entries, workouts, totals and targets |
| web search | The provider's own search, with sources |
| `search_youtube(query)` | Videos with titles, channels, thumbnails and full descriptions (only when the server has a YouTube key) |

Every tool runs as the signed-in person with their own Mealie session. No tool takes a user id.

### Proposals (need a tap)

| Proposal | Card | Tapping it |
|---|---|---|
| Recipes found | One card per recipe: photo if any, name, source, one line on why, a source link | **Add** imports it into Mealie and links to the new recipe |
| Recipe from a photo or pasted text | Name, ingredient count, a preview of the first steps | **Add** saves it to Mealie |
| Meal plan | Days and meals | **Add to plan** creates the entries in Mealie |
| Shopping items | The items, noting ones already on the list | **Add to list** adds them in Mealie |
| Food entry | Description, calories, protein | **Log it** adds it to today |
| Workout | Activity, minutes, effort, calories | **Log it** adds it to today |
| Recipe nutrition | Calories and protein per serving for a recipe that lacks them | **Save to recipe** writes them to Mealie |

A proposal is saved on the server when the model makes it. The button sends only the proposal's id, so the page cannot be altered to do something else, and each proposal works once and expires after a day. This is also what makes web content safe to read: a page written to manipulate an AI can at worst put a bad suggestion on screen.

### Importing a recipe, by source

- **A web page**: Mealie's own link import. The source address is kept on the recipe.
- **Reddit, pasted text, or a photo**: the model writes out the recipe in the standard recipe format and the app hands that to Mealie. The thread or source is kept as the source address.
- **YouTube, recipe in the description**: as for pasted text, with the video as the source address and a "Video" note on the recipe.
- **YouTube, description links to a recipe page**: Mealie's link import of that page, plus a "Video" note with the video link.
- **YouTube, recipe only spoken**: a card with a Watch link and no Add. The app cannot read what is said in a video.

The recipe page in Homeplate shows "Watch the video" when a recipe has a video link.

## Outside the Ask tab

- **Today, Add food**: an "Estimate" button, with an optional photo, fills in calories and protein for the person to adjust.
- **Recipe page**: "Fill in nutrition" on a recipe with none, which makes a nutrition proposal.
- **Me, Settings**: provider, model and key. The key is never shown again after saving.

## Privacy and limits

- What the person types, the photos they attach, and the look-up results (their recipes, plan, list and diary totals) are sent to the AI provider they chose, under their own key.
- Nothing from Kroger is ever sent to an AI provider (Kroger's terms forbid it).
- Photo-based calorie numbers are rough. They are always shown as estimates for the person to correct.
- YouTube allows 100 searches a day for the whole server.
- Weight is not sent to the model.
- Homeplate fetches only card photos itself, and only from public addresses. The recipe page behind a card is fetched by Mealie: once when the card is made (to see whether it can be imported) and again when Add is tapped. Homeplate checks the address is public first, but Mealie resolves and follows it under its own rules. So a hostile page that got itself proposed could at worst make Mealie send one request it cannot read the answer to, or serve a different recipe than the card named. Nothing is saved without a tap.

## Not in this step

Kroger ordering (step 4). Voice. Several saved conversations. Notifications. A pantry inventory. Reading video transcripts.

## Live test results (2026-11-10, real key, `openai/gpt-5-nano`)

1. **Search tool alongside the app's tools: works.** `tools: [{"type":"openrouter:web_search","parameters":{"max_results":5}}, {"type":"function",...}]` on `/chat/completions`. Only the app's function calls come back in `tool_calls`; after the `role:"tool"` reply the model searched and answered with `message.annotations[].url_citation{url,title}`. The two-request fallback is not needed.
2. **Photo plus search in one request: works** (read the photo, searched, cited a recipe).
3. **Reddit: works with the default engine.** With `allowed_domains:["reddit.com"]`, and also with no filter and "Reddit" in the question, it found a real thread, quoted a comment from it and linked it. With `engine:"exa"` plus the filter it ran four searches and then answered as if it had not searched. With `engine:"parallel"` it also found and quoted threads (see the comparison below).
4. **YouTube API:** Google's pages give a default of 100 `search.list` calls a day and 10,000 units for everything else, and name no price on either page read. Not tested live (no key yet).
5. **Fixed format together with tools: does not work, so keep fixed-format requests separate.** Two requests to `openai/gpt-5-nano` (`max_tokens` 3000, effort `low`, strict `json_schema` with name, source_url, ingredients, steps), asking for a pancake recipe from the web (2026-11-10):
   - With the search tool and one function tool: HTTP 200 in 11.3 s, cost 0.15 cents. The search ran (`web_search_requests: 1`, five citations), but the content was a plain-text list of recipes, not JSON. The schema was ignored. No error was returned.
   - Without tools: HTTP 200 in 7.7 s, cost 0.02 cents. Valid JSON matching the schema. It did not search, so the `source_url` came from the model's memory and may not be real.
   - So a fixed format and web search cannot share a request. Plan stays: search in one request, then a second request with no tools that turns the result into the fixed format.

Measured through the app (three questions, `openai/gpt-5-nano`, effort `low`, Parallel turbo search, 2026-11-10): the pizza dough rest question took 5.2 s, the highly rated cinnamon roll question 9.2 s, and the Reddit question 10.2 s. All under the 20 s target. Sources showed under the last two (5 each) and none under the first (no search). Cost: OpenRouter's credit total lags by several seconds, so per-question deltas were unreliable. Over the five app questions (the three above, a rerun of the cinnamon roll question after a fix, and the Gemini run) the account total rose by about 0.55 cents after subtracting the step 5 requests, so about 0.1 cents a question, under the half-cent target. With `google/gemini-2.5-flash-lite` the cinnamon roll question took 4.1 s, showed 5 sources, and OpenRouter did not reject `reasoning`.
Found by the live check: the model sometimes wrote `Title (https://...)` in a Sources list in its text despite the prompt. The app now strips bare parenthesised links. It also sometimes writes its own "Sources" list and short `-` bullet lists. Short bullet lists are plain text and are left. When the answer has source links, a trailing block starting at a "Source:" or "Sources:" line is stripped, and so are lines that hold only a web address.

### Piece 2 live check (2026-11-10, recipe cards)

Run with `scripts/ask-check.mjs` (a real headless Chrome against the local app, real key), 22 of 22 checks on the final code. "Find me some arroz con pollo recipes" came back in 9 to 12 s as four cards, with photos, and no web address in the text. The model searches and calls `propose_recipes` in one request (about 0.14 cents). Add turned a card into "Added to your recipes." without a reload and Mealie had exactly one new recipe; a second tap did not import again; an unknown card id was refused. "Which of my saved recipes use chicken?" was answered through a look-up in 6 to 9 s. No sideways overflow at 375, 390 and 430 px, light and dark. Look-up rounds also worked on `google/gemini-2.5-flash-lite` and `anthropic/claude-haiku-5.5` through OpenRouter.

Mealie's own link import took about a second per page. It answers 400 for a page it cannot read, and some pages parse with no ingredients (those get a card with no Add button). A duplicate import makes a second copy in Mealie, which is why a card works once.

Found along the way, and to build in:

- **Always send `max_tokens`.** Without it the request asks for 65,536 and is refused with a 402 when the balance is low, even for a tiny question.
- **The default search engine is the slow, costly part, and it is a setting.** For `openai/gpt-5-nano` the default is OpenAI's own search. Measured on the same questions (2026-11-10):

  | Search | Reasoning effort | Time | Cost per question |
  |---|---|---|---|
  | OpenRouter tool, default engine (OpenAI native) | default | 20 to 105 s | 1.1 to 4.4 cents |
  | OpenRouter tool, `engine:"parallel"`, `mode:"turbo"` | default | 21 s | 0.17 cents |
  | OpenRouter tool, `engine:"parallel"`, `mode:"turbo"` | `low` | 5 to 9 s | 0.12 to 0.14 cents |
  | Our own `web_search` function backed by a local SearXNG | `low` | about 11 s | 0.02 to 0.03 cents |

  **Decision: OpenRouter's tool with `{"engine":"parallel","mode":"turbo","max_results":5}` and `"reasoning":{"effort":"low"}`.** It answered the recipe and Reddit questions well, returns 600 to 900 characters of page excerpt per citation, and needs nothing extra on the server.
- **SearXNG is a workable fallback, not needed now.** A throwaway local instance (`searxng/searxng`, `search.formats: [html, json]`, limiter off) answered in 1 to 3 s with good recipe, Reddit and YouTube results and thumbnails, through Brave and Google. DuckDuckGo answered it with a CAPTCHA within the first minute, which is the known weakness: it scrapes search sites and they block it without notice. It would be one more container to keep running, returns only short snippets, and needs the app to run the search itself as a look-up tool. Choose it only if OpenRouter's search stops being good or cheap enough.
- With the chosen settings "well under a dollar a month" holds again: about 700 searched questions per dollar.
- The default engine adds about 4,500 input tokens to every request; Parallel adds about 2,000.
- Citations carry no page excerpt (`content` is empty), and addresses can come back with `?utm_source=openai` appended: strip it.
- A 402 has two forms worth telling apart for the person: out of credit, and "in-flight budget" (retry shortly).

## Order of work

1. Settings, the OpenRouter connection, the live tests above, and plain question-and-answer with web search and sources.
2. Look-up tools, the proposal cards, and finding and adding recipes from the web, with photos.
3. The other proposals (plan, shopping list, food, workout, nutrition) and photo input (fridge, recipe photo, meal estimate).
4. YouTube search, and Reddit-focused searching.
5. Claude and Gemini direct keys.

Each is usable on its own and is shown to the owner before the next starts.

## Needed from the owner

- An OpenRouter API key for testing, put in the project's local `.env` file as `OPENROUTER_API_KEY` (not pasted into chat). Light use costs well under a dollar a month.
- Optionally a YouTube API key in the same file as `YOUTUBE_API_KEY`, needed before piece 4.

## References

- Provider request formats and what is verified: `docs/research/2026-11-09-ai-providers.md`
- Kroger API and terms: `docs/research/2026-11-09-kroger-api.md`
