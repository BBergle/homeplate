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

## Not in this step

Kroger ordering (step 4). Voice. Several saved conversations. Notifications. A pantry inventory. Reading video transcripts.

## Unverified, to settle first with a real key

The first piece of work is a live test, before anything else is built on these:

1. The exact request for OpenRouter's search tool alongside the app's tools (the docs name the fields but show no worked example).
2. Whether a photo and a web search can go in the same request.
3. How well searches surface and read Reddit threads.
4. That the YouTube API is free at these volumes (believed so; the page read did not state a price).
5. Whether the model can be made to return a fixed data format (for the standard recipe format and for estimates) in the same request that uses tools.

If 1 fails, the fallback is two requests per message: one to search, one to produce cards.

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
