# AI provider integration reference (httpx, BYO key)

Researched 2026-11-09. Legend: **[V]** = verified against the vendor page named; **[V-live]** = verified by calling the public unauthenticated `https://openrouter.ai/api/v1/models` today; **[NV]** = not verified (page did not load, page silent, or inferred).
Note on method: OpenRouter/Google pages were read through a summarising fetcher (it paraphrases, and sometimes truncates); Anthropic pages came back as raw markdown (highest confidence). JSON below marked "from docs" is copied/adapted from a doc example; anything else is built from documented field names and flagged.

---------------------------------------------------------------------------
## 1. OpenRouter (first priority)

Base: `https://openrouter.ai/api/v1`. Chat endpoint: `POST /chat/completions` (OpenAI shape). Models: `GET /models`.

### 1.1 Headers
```
Authorization: Bearer <user OR key>
Content-Type: application/json
HTTP-Referer: https://yourapp.example        # app URL, primary identifier for rankings. [V https://openrouter.ai/docs/app-attribution]
X-OpenRouter-Title: YourApp                  # current name for display title. [V same]
X-Title: YourApp                             # legacy, "still supported for backwards compatibility". [V same]
```
Both attribution headers are optional for function; Title without Referer does not create an app page. [V same]

### 1.2 Plain chat (minimal)
```json
{"model":"openai/gpt-5-nano","messages":[{"role":"user","content":"Hello"}]}
```
Response: `choices[0].message.content`, `choices[0].finish_reason`, `usage`. [NV for exact envelope on a doc page; standard OpenAI shape; the live models API lists `/api/v1/chat/completions` as an endpoint for models [V-live]]

### 1.3 Web search: three forms, which one is recommended
Docs say: the `web` plugin and the `:online` suffix are **deprecated**: "Use the `openrouter:web_search` server tool instead." The server tool "lets the model decide whether and how often to search, while the plugin always searches once per request." [V https://openrouter.ai/docs/guides/features/server-tools/web-search]
So: **recommended = server tool.** `:online` is documented as a shortcut for `plugins:[{"id":"web"}]`. [V https://openrouter.ai/docs/guides/features/plugins/web-search]

**A. Server tool (recommended).** Goes in `tools` next to function tools. The doc example uses a Responses-style body (`input`, `max_tool_calls`); the chat-completions schema also lists `OpenRouterWebSearchServerTool` in the `tools` union, with `parameters` of type `WebSearchConfig`. [V https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion.md] The doc page itself does not print a chat-completions example, so the body below is built from those field names [NV until live test]:
```json
{
  "model": "openai/gpt-5-nano",
  "messages": [{"role":"user","content":"What's the latest on X?"}],
  "tools": [
    {"type":"openrouter:web_search",
     "parameters":{"max_results":5,"max_total_results":15,"engine":"auto",
                   "allowed_domains":["reddit.com"]}}
  ]
}
```
Parameters (`tools[].parameters`) [V server-tools/web-search page]:
- `engine`: `auto` (default) | `native` | `exa` | `firecrawl` | `parallel` | `perplexity`. `auto` = native if provider supports, else Exa.
- `mode`: engine-specific (Exa: instant, fast, auto, deep-lite, deep, deep-reasoning; Parallel: turbo, fast, basic, advanced).
- `max_results`: per search call, 1-25 (1-20 Perplexity), default 5.
- `max_uses`: max searches per request; forwarded only to Anthropic native search.
- `max_total_results`: cap across all searches in one request.
- `search_context_size`: low|medium|high. `max_characters`: 1-100000 per result.
- `user_location` {city, region, country, timezone}: native only.
- `allowed_domains` / `excluded_domains` (note the names differ from the plugin's `include_domains`/`exclude_domains`).
- Top-level `max_tool_calls` (shared server-tool step budget, default and max 30) is documented as a sibling of `input`/`tools` on that page.
- Domain filter support: "Exa supports both lists at once. Parallel, Firecrawl, Perplexity, and Anthropic native search accept only one list at a time. Perplexity rejects requests with both (400). OpenAI native search ignores `excluded_domains`. Google native search doesn't support domain filters."

**B. Plugin (deprecated).** [V plugins/web-search page]
```json
{"model":"openai/gpt-5-nano","messages":[...],
 "plugins":[{"id":"web","engine":"exa","max_results":5,
             "search_prompt":"Some relevant web results:",
             "include_domains":["reddit.com","*.substack.com"],
             "exclude_domains":["example.org"]}]}
```
Plugin params: `engine` (native|exa|firecrawl|parallel|perplexity|unspecified), `mode`, `max_results` (default 5), `search_prompt`, `include_domains`, `exclude_domains` (wildcards `*.x.com` and paths `openai.com/blog` supported). Plugin always runs exactly one search per request and injects results as text into the prompt.

**C. `:online` suffix.** `"model":"openai/gpt-5.2:online"` == `plugins:[{"id":"web"}]`; also works on `:free` models (`...:free:online`). [V same page] Deprecated.

Engine default: native for OpenAI, Anthropic, Google, Perplexity, SpaceXAI models; Exa for everything else. [V plugins page]

### 1.4 KEY QUESTION: search + function tools + images in one request
- Tools: **YES, documented.** "Server tools work alongside your own user-defined tools. You can include both in the same request." "The model can call any combination of server tools and user-defined tools." "OpenRouter executes the server tools automatically, while your application handles the user-defined tool calls as usual." [V https://openrouter.ai/docs/guides/features/server-tools (fetched via the summariser; page text, not a raw copy)]
  Caveat: the same page's examples are Responses-API style; it does not explicitly say the chat-completions endpoint behaves identically, but the chat-completions OpenAPI schema lists the server tools in the `tools` union [V]. Live-test.
- Images + search: **not addressed** by any OpenRouter page I read [NV]. Images are ordinary user content parts; no restriction documented. For native-engine models the underlying vendor rules apply (see Claude/Gemini sections: no restriction documented either).
- Structured output + tools/search together: OpenRouter page "doesn't say" [NV]. Per-endpoint support; check `structured_outputs` in model's `supported_parameters`.

### 1.5 Function tool definition, tool call, follow-up (chat completions)
Tool definition (nested under `function`): [V https://openrouter.ai/docs/guides/features/tool-calling]
```json
{"type":"function","function":{"name":"add_to_shopping_list","description":"...",
 "parameters":{"type":"object","properties":{"items":{"type":"array","items":{"type":"string"}}},"required":["items"]}}}
```
Assistant response: `choices[0].message.content` may be `null`, `choices[0].message.tool_calls[]` each `{"id":"call_abc123","type":"function","function":{"name":"...","arguments":"{\"items\":[\"milk\"]}"}}`. `arguments` is a JSON **string**: `json.loads` it. [V same page]
Follow-up: append the assistant message verbatim (with its `tool_calls`), then one message per call:
```json
{"role":"tool","tool_call_id":"call_abc123","content":"{\"ok\":true}"}
```
[V same page for `role:"tool"` + `tool_call_id`]. "The `tools` parameter must be included in every request, including the follow-up request that carries tool results." [V]
Several calls in one response: `tool_calls` has several entries; answer each with its own `role:"tool"` message (matched by `tool_call_id`). The page has no explicit multi-call JSON example [V that it is silent; the one-message-per-call rule is the OpenAI convention, NV on OpenRouter page]. `parallel_tool_calls:false` forces one at a time (default true for most models). `tool_choice`: `"auto"`, `"none"`, `{"type":"function","function":{"name":"..."}}`. [V]
Proposal tools: read `tool_calls[i].function.arguments`, render the card, and stop; no follow-up request is required by the API. If the conversation continues later, the history will contain an assistant `tool_calls` message, and OpenAI-style APIs normally require matching `tool` messages, so store a placeholder result (e.g. `{"status":"shown_to_user"}`) before the next user turn [NV for OpenRouter; required-by rule verified for Claude only, section 3.4].

### 1.6 Citations
Annotations on the assistant message, OpenAI schema: [V plugins page; the server-tool page says excerpts are "surfaced to API callers via `url_citation` annotations"]
```json
"message":{"role":"assistant","content":"...","annotations":[
 {"type":"url_citation","url_citation":{"url":"https://...","title":"...","content":"...","start_index":100,"end_index":200}}]}
```
`start_index`/`end_index` locate the span inside `message.content` (units, chars vs bytes: NV). `content` added by OpenRouter when available. Docs say the schema applies to all models including native-only. Usage: `usage.server_tool_use_details.web_search_requests` counts queries. [V server-tools page] Not verified: whether the chat-completions *schema page* defines `annotations` (the part I read did not; it was truncated, and a 126k-char tail was partly unread).

### 1.7 Images
Content part (OpenAI shape):
```json
{"role":"user","content":[
 {"type":"text","text":"What's in this fridge?"},
 {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,/9j/4AAQ..."}}]}
```
Doc facts: base64 data URLs accepted in `image_url`; types `image/png, image/jpeg, image/webp, image/gif`; "number of images ... varies per provider and per model"; size limit **not stated**. [V https://openrouter.ai/docs/guides/overview/multimodal/image-understanding, but that fetched page described the Responses form (`input_image`); the chat-completions `image_url` + `data:` shape is NV on the page, supported only by a search-result summary of the official guide.] Put text first, then images (doc advice). Model must have `"image"` in `architecture.input_modalities`.

### 1.8 JSON / structured output
```json
"response_format":{"type":"json_schema","json_schema":{"name":"recipe","strict":true,
  "schema":{"type":"object","properties":{"name":{"type":"string"}},"required":["name"],"additionalProperties":false}}}
```
[V https://openrouter.ai/docs/guides/features/structured-outputs] Unsupported model => request errors. `"require_parameters": true` in provider preferences routes only to endpoints supporting every param. Response Healing plugin can repair invalid JSON on non-streaming requests. Combining with tools: page silent [NV]. Other `response_format.type` values in schema: text, json_object, grammar, python [V].

### 1.9 Domain filtering / Reddit
- Restrict or bias to Reddit: `allowed_domains:["reddit.com"]` (server tool) or `include_domains:["reddit.com"]` (plugin). Works with Exa (both lists), Parallel, Firecrawl, Perplexity (one list at a time); Anthropic native: one list at a time; OpenAI native ignores excluded only; Google native: no domain filters at all. [V]
- Docs say nothing about which engine indexes Reddit well; the only Reddit mention in the plugin page is an `exclude_domains:["reddit.com"]` example. [V by absence] Whether Exa/Parallel actually return reddit.com results is **NV** (live test).
- "Bias" (soft preference) is not a documented feature; filters are hard include/exclude.

### 1.10 Pricing
Server tool / plugin per-search, on top of token cost [V both pages]: Exa $0.007/request (instant/fast/auto), $0.012 (deep-lite/deep), $0.015 (deep-reasoning), up to 10 results included then $0.001 each; Parallel $0.001 (turbo/fast) or $0.005 (basic/advanced); Perplexity $0.005; Firecrawl $0.005 + $0.0125 per result; native = provider pass-through.
Per-model native search price is `pricing.web_search` (USD per search) in the models API [V schema + V-live values].
Live (2026-11-09) cheapest model with tools + image + structured_outputs + priced native web search, excluding `:free`/`:batch`/router ids [V-live]:
- `openai/gpt-5-nano`: prompt $0.05/M, completion $0.40/M, `web_search` $0.01/search. (Reasoning model; check latency.)
- Next: `meta/muse-spark-1.2-contributor` $0.10/$0.20, search $0.0025; `google/gemini-2.5-flash-lite` $0.10/$0.40, search $0.014; `anthropic/claude-haiku-5.5` $0.10/$0.50, search $0.01 (>100k-token prompts cost more); `google/gemini-3.5-flash-lite` $0.30/$2.50, search $0.014.
- Models without `pricing.web_search` can still search via Exa/Parallel (engine fallback) at the per-request prices above, e.g. `deepseek/deepseek-v4.1-flash` (tools + image + structured_outputs, ~$0.051/$0.567 per M [V-live]); combined behaviour [NV].
Prices change; read them from `/models` at runtime.

### 1.11 Errors [V https://openrouter.ai/docs/api-reference/errors]
Body: `{"error":{"code":<int>,"message":"...","metadata":{...}}}`; HTTP status equals `error.code` for request errors. Errors during generation can arrive with HTTP 200 (in body) or as an SSE event, so check for a top-level `error` key even on 200.
- 401: key invalid/disabled. 402: insufficient credits (no `Retry-After`, do not retry). 429: rate limited (honor `Retry-After`). 400: bad params. 408 timeout. 502 model down/invalid response. 503 no provider meets routing needs. 403: moderation / budget / guardrail (metadata: `limit_source`, `reasons`, ...). Provider errors carry `metadata.error_type`, `metadata.provider_code`.
- "Model does not support tools/images": exact message/status NOT documented on the pages read [NV]. Prevent it by checking the models API (below); for structured outputs the doc says the request "fails with an error indicating lack of support".

### 1.12 Capability discovery (models API) [V https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties.md + V-live]
`GET https://openrouter.ai/api/v1/models` (no auth needed; 464 models today). Per model:
- `architecture.input_modalities`: array of `text|image|file|audio|video`. Vision = contains `"image"`.
- `supported_parameters`: array incl. `tools`, `tool_choice`, `parallel_tool_calls`, `structured_outputs`, `response_format`, `web_search_options`, `reasoning`, ... Tools = contains `"tools"`; strict JSON schema = `"structured_outputs"`.
- `pricing`: strings in USD per token (`prompt`, `completion`, optional `image`, `request`, `web_search` = USD per search, cache fields). `context_length`, `top_provider.max_completion_tokens`, `endpoints` (e.g. `/api/v1/chat/completions`).
- Query filter: `?supported_parameters=tools` (comma-separated; AND/OR semantics unstated).
- **Web search is NOT a per-model flag you must have**: `web_search_options` appears on only ~18 models today [V-live] (native-search models like perplexity/*, sakana/*, openai/gpt-4o*), while the server tool works on any model via Exa/Parallel fallback. So: warn on missing `tools` / `image`; treat web search as available on every model, and show native-vs-Exa cost using `pricing.web_search` when present. [Inference, flagged.]
- Model id: use `id` exactly as listed (`vendor/name`). No suffix needed. Optional suffixes: `:online` (deprecated), `:free`, `:batch` (appears as separate ids in the live list), `:nitro`/`:floor` style variants exist in OpenRouter generally [NV]. A user-chosen id needs no suffix; do not append `:online`, use the server tool.
- Caution: per-model pricing may be negative for routers (`openrouter/auto` shows -1) [V-live]; skip those in "cheapest" computations.

---------------------------------------------------------------------------
## 2. Google Gemini API

IMPORTANT: Google's docs have moved to `aistudio.google.com/docs/...` (301 from ai.google.dev) and now lead with the **Interactions API** (`/v1beta/interactions`); `generateContent` is "legacy" but "remains fully supported". [V https://aistudio.google.com/docs/interactions] The pages I could load describe only Interactions; I could NOT load a current generateContent page, so legacy `generateContent` request shapes below are **not given** (not invented). The Interactions API requires `Api-Revision: 2026-05-20` for the new `steps` schema in REST ("After May 26, the new schema is the default... On June 8, the legacy schema is removed and the header is ignored." [V https://aistudio.google.com/docs/interactions-breaking-changes-may-2026]). Send the header anyway; it is harmless.

### 2.1 Endpoint, headers, plain chat
```
POST https://generativelanguage.googleapis.com/v1beta/interactions
x-goog-api-key: <user key>
Content-Type: application/json
Api-Revision: 2026-05-20
```
```json
{"model":"gemini-3.8-flash","input":"Your prompt here"}
```
[V interactions page + google-search page]. Response: `id`, `status` (`in_progress|requires_action|completed|failed|cancelled|incomplete|requires_continuation`), `steps[]`, `usage` (`total_input_tokens`, `total_output_tokens`, `total_thought_tokens`, `total_tool_use_tokens`, ...). Final text: step `{"type":"model_output","content":[{"type":"text","text":"..."}]}`. [V https://aistudio.google.com/api-reference/interactions-api]. Other body fields: `system_instruction`, `generation_config` (e.g. `thinking_level`, `temperature`), `tools`, `response_format`, `previous_interaction_id`, `store`, `stream`. "interaction-scoped": `system_instruction`, `tools`, `generation_config` must be re-sent on every new interaction. [V]
State: `store` defaults true (server keeps history; chain with `previous_interaction_id`). `store:false` = stateless, you resend history ("pass the prior response's `steps` array in `input`, appending your new turn as a `user_input` step"; no full example on the page) [V partial; exact stateless payload NV].
Model ids seen in docs: `gemini-3.8-flash`, `gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-4-argon`, 2.5 family.

### 2.2 Web search (Google Search grounding)
```json
{"model":"gemini-3.8-flash","input":"Who won the euro 2024?","tools":[{"type":"google_search"}]}
```
[V google-search page, exact curl]. No parameters documented for the tool (no max uses, no domain filter, no exclude list): "The page doesn't mention any" [V by absence]. `google_search` is for all current models; old models use `google_search_retrieval`. Supported: Gemini 4 Argon, 3.8 Flash, 3.6 Flash, 3.5 Flash-Lite, 3.1 Flash Image/Pro Preview, 3 Pro Image Preview, 3 Flash Preview, 2.5 Pro/Flash/Flash-Lite, 2.0 Flash. [V]
**Domain restriction / Reddit: NOT possible per docs** (no parameter). A `site:reddit.com` in the prompt is the only lever [NV, untested heuristic]. Nothing documented about which sources Google Search returns beyond "Google Search".
Response steps: `google_search_call` (`arguments.queries`, `search_type` = `web_search|image_search`), `google_search_result` (`call_id`, `search_suggestions` = HTML snippet you must display per Google's grounding terms [NV on the display requirement]), then `model_output` whose text item carries `annotations`.

Citations: on the `model_output` text content item:
```json
{"type":"text","text":"...","annotations":[{"type":"url_citation","url":"https://...","title":"...","start_index":0,"end_index":42}]}
```
`start_index` is in **bytes**, `end_index` exclusive (UTF-8 bytes of the text; slice `text.encode()[s:e]`). [V Interactions reference UrlCitation]. (Older generateContent used `groundingMetadata`; the Interactions page documents none of it.)

### 2.3 KEY QUESTION: search + function tools (+ images)
- Documented: "Gemini 3 models also support combining these built-in tools with custom tools (function calling)." [V https://aistudio.google.com/docs/google-search]. Tool-combination page: "preview", "supported for Gemini 4 and Gemini 3 models"; with tool context circulation enabled use `validated` mode: "`auto` mode is not supported." Also: if system instruction/function descriptions carry conflicting location/time info, search "may not combine well". [V https://aistudio.google.com/docs/tool-combination]
- NOT supported / not documented: Gemini 2.5 and older with Interactions combination (page says Gemini 4 and 3 only). I could not load any page that states the older generateContent restriction (e.g. "can't mix google_search with function calling on 2.x"); that restriction is **NV** here. Treat 2.5-and-older as "no mixing" for safety.
- Exact working request (from the doc):
```json
{"model":"gemini-3.8-flash",
 "input":"What is the northernmost city in the United States? What's the weather like there today?",
 "tools":[{"type":"google_search"},
  {"type":"function","name":"getWeather","description":"Get the weather in a given location",
   "parameters":{"type":"object","properties":{"location":{"type":"string","description":"The city and state"}},"required":["location"]}}]}
```
[V tool-combination page; no `tool_choice` set in the example]. Setting `"generation_config":{"tool_choice":"validated"}` per the function-calling page ("tool_choice in generation_config: auto, any, none, validated") and `ToolChoiceConfig{mode, allowed_tools{mode,tools[]}}` in the reference [V]; whether the combination example needs it is NV (live test; the page's example works without).
- Images + search: no restriction stated anywhere I read [NV, assume allowed; image is just another `input` item].
- Workaround if a model/version rejects the mix: expose `web_search(query)` as a function tool; when called, run a separate **search-only** request (`tools:[{"type":"google_search"}]`, no functions, same model) and return the answer text + citations as the `function_result`. This works on every Gemini version because the two features never share a request.

### 2.4 Function calling
Declaration (flat, top-level, `type:"function"`): `{"type":"function","name","description","parameters":<JSON Schema>}`. [V]
Call in response: a step `{"type":"function_call","id":"...","name":"...","arguments":{...}}` (`arguments` is an **object**, not a string). Status becomes `requires_action`. [V reference + breaking-changes page]
Follow-up (stateful):
```json
{"model":"gemini-3.8-flash","previous_interaction_id":"INTERACTION_ID",
 "input":[{"type":"function_result","name":"getWeather","call_id":"CALL_ID",
           "result":[{"type":"text","text":"{\"temp_f\":12}"}]}]}
```
[V function-calling page]. `function_result` fields: `result` (text/image content array, object, or string), `call_id` (required), `name`, `is_error`. [V reference]. Tools/system_instruction/generation_config must be re-sent. Thought signatures: with `previous_interaction_id` the server handles `id` and `signature`; in stateless mode you must send back steps exactly as received including `thought` steps and `signature`s (SDKs do it by appending the response object). [V tool-combination page]
Multiple calls: "The model supports calling multiple functions in a single turn." [V]; how to answer several at once is **NV** (no example). Expected: several `function_call` steps in `steps`; send several `function_result` items in the `input` array, one per `call_id`. [inference]
Proposal tools / ending turn without follow-up: nothing documented about an unanswered `requires_action` interaction. With `store:true`, simplest is to start the next user turn from a new interaction with your own summary, or send `function_result` placeholders first. [NV]
Streaming + tools: streamed function call sets status `requires_action`; "Clients must accumulate the argument deltas before returning the result." [search-result summary of Google's docs; NV direct]

### 2.5 Images
```json
{"model":"gemini-3.8-flash","input":[
  {"type":"text","text":"Caption this image."},
  {"type":"image","data":"<base64, no data: prefix>","mime_type":"image/jpeg"}]}
```
[V https://aistudio.google.com/docs/image-understanding]. Accepted (guide page): png, jpeg, webp, heic, heif; the API reference enum also lists gif, bmp, tiff. Limit: inline data counts toward a **20 MB total request** (prompt + system + inline bytes); larger -> File API. Optional `media_resolution` (Gemini 3) / `resolution` `low|medium|high|ultra_high` on ImageContent. [V]

### 2.6 JSON output
```json
{"model":"gemini-3.8-flash","input":"Turn this recipe into schema.org Recipe JSON: ...",
 "response_format":{"type":"text","mime_type":"application/json","schema":{"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}}}
```
[V https://aistudio.google.com/docs/structured-output]. Combining with tools: "structured outputs can also be combined with URL Context, Code Execution, File Search, and Function Calling" and example shows `tools:[google_search,url_context]` + `response_format`; "Preview: This feature is available only to Gemini 3 series models." [V]. Supported schema subset: types, `properties/required/additionalProperties`, `enum/format`, `minimum/maximum`, `items/prefixItems/minItems/maxItems`; `minLength/maxLength/uniqueItems` etc. are ignored (validate yourself); schema too complex => 400 INVALID_ARGUMENT. [V]
Because the final answer is shaped by `response_format`, a search+function+JSON triple in one request is NV; do JSON extraction as a separate request.

### 2.6b OpenAI-compat endpoint
Base `https://generativelanguage.googleapis.com/v1beta/openai/`, "still in beta". Chat, streaming, function calling, structured output, base64 `image_url`, embeddings supported. Web-search for chat completions: **page does not say**; grounding documented only for image generation through `extra_body` (`gemini-3-pro-image-preview`). [V https://aistudio.google.com/docs/openai] => treat as lost.

### 2.7 Pricing [V https://aistudio.google.com/docs/pricing]
- Search grounding, Gemini 3+: 5,000 free search requests/month shared across Gemini 3+ models, then $14 per 1,000 search *queries the model executes*; cap 1,500 requests/day (paid tier default). "The free tier does not include grounding for 3.5 Flash-Lite."
- Gemini 2.5 family: billed per grounded prompt, $35 per 1,000 (Flash-Lite page row).
- Tokens (per M, standard): `gemini-3.5-flash-lite` $0.30 in / $2.50 out (cheapest Gemini 3 with search + tools + vision; combination is documented for "Gemini 3 and 4", Flash-Lite combination support not separately confirmed [NV]); `gemini-3.8-flash` $0.75/$3.75 through 2026-12-31 then $1.50/$7.50; `gemini-2.5-flash-lite` $0.10/$0.40 (but $35/1000 grounding, no documented mixing).

### 2.8 Errors
- Interactions-style (api-errors page): `{"error":{"code":"invalid_request","message":"..."}}`; table: 401 `authentication` (key missing/invalid/expired), 429 `quota_exceeded` (daily) and `rate_limit_exceeded`, 501 `unimplemented` (feature unsupported by model), 404 `model_not_found`. [V https://aistudio.google.com/docs/api-errors]
- Troubleshooting page uses Google-style statuses: 400 INVALID_ARGUMENT ("invalid API keys, depleted Prepay credits, or bad syntax" are 400-class), 403 PERMISSION_DENIED, 429 RESOURCE_EXHAUSTED, 503 UNAVAILABLE; retry 429/503/5xx with backoff. [V https://aistudio.google.com/docs/troubleshooting]
- The two pages disagree on shape/codes (invalid key = 401 `authentication` vs 400): handle by HTTP status plus string match on message. [Flag]
- Capability discovery: Gemini `GET /v1beta/models` supportedGenerationMethods exist but I did not verify a tools/vision/search capability flag [NV]. Use a static allowlist.

---------------------------------------------------------------------------
## 3. Anthropic Claude API

All facts below are from raw platform.claude.com pages [V].

### 3.1 Endpoint, headers, plain chat
```
POST https://api.anthropic.com/v1/messages
x-api-key: <user key>
anthropic-version: 2026-10-21      # docs: "you must send an anthropic-version request header. For example, anthropic-version: 2026-10-21" and "Anthropic recommends using the latest"
content-type: application/json
```
```json
{"model":"claude-haiku-5-5","max_tokens":1024,"messages":[{"role":"user","content":"Hello"}]}
```
Version caveats [V https://platform.claude.com/docs/en/api/versioning]: in `2026-10-21`, `temperature`, `top_p`, `top_k` are **removed** (any of them => 400 on every model); older `2023-06-01` is still listed in the version history (still accepted: NV). Don't send sampling params. `max_tokens` is required. Model ids (no date suffix): `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-fable-5-2`. [V models overview]. Response: `content[]` blocks, `stop_reason`, `usage`.

### 3.2 Web search
Tool type strings: `web_search_20250305` (basic), `web_search_20260209` (adds dynamic filtering via code execution), `web_search_20260318` (adds `response_inclusion`). Name must be `"web_search"`.
**Simplest: use `web_search_20250305`** (defaults to direct calls, no hidden code-execution step). `_20260209`+ default to code execution caller and need `allowed_callers:["direct"]` on models without programmatic tool calling, else 400.
```json
{"type":"web_search_20250305","name":"web_search","max_uses":5,
 "allowed_domains":["reddit.com"],
 "user_location":{"type":"approximate","city":"Austin","region":"Texas","country":"US","timezone":"America/Chicago"}}
```
Rules [V web-search-tool + server-tools pages]: `allowed_domains` **or** `blocked_domains`, not both (400). Bare domains, no scheme; subdomains included; path prefixes supported (`example.com/blog`); wildcard only in the path (`example.com/*`), `*.example.com` is invalid; org-level restrictions in Console must contain request-level lists. Max uses: failed searches count; exceeding yields `web_search_tool_result_error` `max_uses_exceeded`. `user_location.country` = ISO alpha-2. Web search can be disabled by org admin => 400 `invalid_request_error`. Check support: Models API `capabilities.server_tools.web_search.supported`. [V models overview]
Reddit: `allowed_domains:["reddit.com"]` is syntactically valid; the docs say nothing about whether Anthropic's search backend indexes/returns Reddit, so results may be empty [NV].

### 3.3 KEY QUESTION: search + function tools + images
- Allowed. "Claude can call a server tool and a client tool in the same group of parallel tool calls" and the API returns `stop_reason:"tool_use"` with the `server_tool_use` block lacking a result and the client `tool_use`; the API "runs the tool when you return the client `tool_result` blocks in your next request". [V server-tools page, "Mixing server tools and client tools in one turn"] (example there uses web_fetch; the web search page says the same: "If Claude calls web search and one of your client tools in the same group of parallel tool calls, the API returns `stop_reason: "tool_use"` instead and does not run the search yet.")
- Images + web search: no restriction documented; web search "Availability: every model"; vision supported on all current models [V]. (Not explicitly tested together: NV.)
- Follow-up rule: next user message must contain **only** `tool_result` blocks (text after them makes the API 400 when a server tool is pending); keep the same `tools` array. Otherwise (client tools only) text may follow results; `tool_result` blocks must come first. [V]

### 3.4 Function tools
```json
{"name":"get_weather","description":"...","input_schema":{"type":"object","properties":{"location":{"type":"string"}},"required":["location"]}}
```
(optional `strict:true`, `input_examples`.) Name regex `^[a-zA-Z0-9_-]{1,128}$`. [V define-tools]
Response: `stop_reason:"tool_use"`, `content[]` may contain `text` then `{"type":"tool_use","id":"toolu_...","name":"get_weather","input":{...}}` (`input` is an **object**). Several `tool_use` blocks in one response are normal (parallel).
Follow-up: append the whole assistant `content` as-is, then ONE user message:
```json
{"role":"user","content":[
  {"type":"tool_result","tool_use_id":"toolu_A","content":"15 degrees"},
  {"type":"tool_result","tool_use_id":"toolu_B","content":"err","is_error":true}]}
```
Every `tool_use` id needs a `tool_result` in the very next message, results first. Error if not: "`tool_use` ids were found without `tool_result` blocks immediately after". [V handle-tool-calls]
Proposal tools: ending the turn with no follow-up is fine; but the stored history still has an unanswered `tool_use`, so before the next user turn send a `tool_result` placeholder (e.g. "Shown to user as a card; awaiting confirmation") in the same user message as the user's next text (text after results is allowed when only client tools are pending). [V rule; placeholder idea is inference]
`tool_choice`: `auto` (default), `any`, `tool`, `none`. **Forced use (`any`/`tool`) returns 400 on Fable 5.2, Mythos 5.2, Opus 5.5, Sonnet 5.5, Fable 5.1, Mythos 5.1** ("tool_choice: type "tool" and "any" are not supported for this model."), and with manual extended thinking. Haiku 5.5 is not in that list. `disable_parallel_tool_use`: not read on the pages fetched [NV]. [V define-tools + errors]

### 3.5 Citations
Text blocks carry `citations` when web search results were used:
```json
{"type":"text","text":"Claude Shannon was born on April 30, 1916","citations":[
 {"type":"web_search_result_location","url":"https://...","title":"...","encrypted_index":"Eo8B...","cited_text":"(<=150 chars)"}]}
```
Mapping: each cited `text` block is the cited span (no char offsets; one block = one claim); concatenate `text` blocks in order for the answer and attach that block's `citations`. Source list: `web_search_tool_result.content[]` items `{url,title,page_age,encrypted_content}`. Multi-turn: send assistant blocks back unmodified, including `encrypted_content`/`encrypted_index`, or 400. `server_tool_use` block: `{"type":"server_tool_use","id":"srvtoolu_..","name":"web_search","input":{"query":"..."}}`. `usage.server_tool_use.web_search_requests`. Display obligation: "citations must be included to the original source" when showing output. [V web-search-tool]
`stop_reason:"pause_turn"`: resend the assistant content unchanged (same tools) to continue; cap loops. Search errors come as HTTP 200 with `web_search_tool_result_error` and `error_code`: `too_many_requests, invalid_tool_input, max_uses_exceeded, query_too_long, request_too_large, unavailable`. [V]

### 3.6 Images
```json
{"role":"user","content":[
 {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":"/9j/4AAQ..."}},
 {"type":"text","text":"What's in this fridge?"}]}
```
[V vision page]. Types: jpeg, png, gif, webp (animated: first frame only). Limits: 10 MB per image (base64-encoded) on the Claude API; max dimensions 8000x8000 px (stricter above 20 images per request); up to 600 images per request (100 for 200k-context models); request cap 128 MB. [V vision + errors pages] Image-then-text ordering is what the docs' examples use.

### 3.7 JSON output
`output_config.format`:
```json
{"output_config":{"format":{"type":"json_schema","schema":{"type":"object","properties":{"name":{"type":"string"}},"required":["name"],"additionalProperties":false}}}}
```
[V structured-outputs]. Needs `additionalProperties:false` on objects; no `minimum/maximum`, `minLength/maxLength`; `minItems` only 0/1; no recursion. Supported on Haiku 5.5, Sonnet 5.5, Opus 5.5, Fable 5.2, etc. Combinable with `strict:true` tools [V]. Combination with web search/citations: **NV** (page section truncated; Anthropic generally disallows citations with structured outputs, not confirmed here). Plan JSON extraction as its own request.

### 3.8 Pricing [V https://platform.claude.com/docs/en/about-claude/pricing]
Web search $10 per 1,000 searches + tokens for results; failed searches not billed. Tokens per M: Haiku 5.5 $0.10 in / $0.50 out (prompts <=100k; $0.50/$2.50 above); Sonnet 5.5 $2/$10; Opus 5.5 $4/$20; Fable 5.2 $8/$40. **Cheapest capable: `claude-haiku-5-5`** (tools + vision + web search + structured outputs all listed for it).

### 3.9 Errors [V https://platform.claude.com/docs/en/api/errors]
Shape: `{"type":"error","error":{"type":"authentication_error","message":"..."},"request_id":"req_..."}`.
401 `authentication_error` (bad key); 402 `billing_error`; 403 `permission_error`; 400 `invalid_request_error` (also for hitting a spend limit you set, and for malformed/unsupported params: e.g. removed sampling params, forced tool use, unsupported tool types: "'<model>' does not support tool types: ..."); 413 `request_too_large`; 429 `rate_limit_error` (a tier spend-cap 429 has no `retry-after`: don't retry); 500 `api_error`; 504 `timeout_error`; 529 `overloaded_error`. "Insufficient credits": documented as 402 `billing_error` (an older "credit balance is too low" 400 message: NV today). Model without image/tool support: 400 `invalid_request_error`, exact text NV; use Models API `capabilities` to pre-check (`GET /v1/models`; image_input/tool-use field names NV, `server_tools.web_search.supported` verified).
Mid-stream errors arrive as SSE error events after a 200.

### 3.10 OpenAI-compat endpoint [V https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk]
Base `https://api.anthropic.com/v1/` (chat completions). Docs: "primarily intended to test and compare model capabilities, and is not considered a long-term or production-ready solution for most use cases." Supported: text, `image_url` (base64/URL; `detail` ignored), function tools (`strict` ignored, `parallel_tool_calls` ok), `response_format` only `json_schema` with `strict:true`. NOT supported: audio/file parts (400), prompt caching, thinking output, `n>1`; no mention of a web-search tool or citations in the compat tables => **web search and citations are unavailable** (use native Messages API). Forced `tool_choice` 400s on the same models as above.

---------------------------------------------------------------------------
## 4. Comparison table (current docs)

| Need | OpenRouter (chat completions) | Gemini native (Interactions) | Claude native (Messages) |
|---|---|---|---|
| 1. Web search + citations | `tools:[{"type":"openrouter:web_search","parameters":{...}}]`; citations `message.annotations[].url_citation{url,title,content,start_index,end_index}`. Any model (native or Exa). | `tools:[{"type":"google_search"}]`; citations `url_citation{url,title,start_index,end_index}` (bytes) on `model_output` text items; must show `search_suggestions`. No params. | `{"type":"web_search_20250305","name":"web_search",max_uses,allowed_domains|blocked_domains,user_location}`; citations `citations[]` `web_search_result_location{url,title,cited_text,encrypted_index}` per text block. |
| 2. Function tools (~10) | `tool_calls[].function.arguments` (JSON string); reply `role:"tool"` + `tool_call_id`, one per call. | `function_call` step `{id,name,arguments(object)}`; reply `function_result{call_id,name,result}` with `previous_interaction_id` (or stateless: resend steps incl. signatures). Multi-call answering NV. | `tool_use{id,name,input(object)}`; reply one user message of `tool_result{tool_use_id,content}` blocks, results first. |
| 3. Image (base64) | `image_url.url="data:image/jpeg;base64,..."`; png/jpeg/webp/gif; size limit not documented; model needs `image` modality. | `{"type":"image","data":b64,"mime_type":..}`; png/jpeg/webp/heic/heif; 20 MB total request. | `{"type":"image","source":{"type":"base64","media_type","data"}}`; jpeg/png/gif/webp; 10 MB/image (b64), 8000 px. |
| 4. JSON output | `response_format:{type:"json_schema",json_schema:{name,strict,schema}}` (model must list `structured_outputs`). | `response_format:{type:"text",mime_type:"application/json",schema}`; Gemini 3 only for tool combos. | `output_config.format:{type:"json_schema",schema}` (needs `additionalProperties:false`). |
| 5. Search + function tools in same request | YES documented ("Server tools work alongside your own user-defined tools"). Chat-completions example NV. | YES for Gemini 3/4 ("Gemini 3 models also support combining..."; preview; `validated` mode, not `auto`, when circulation on). Older: not documented; use search-as-function workaround. | YES documented (mixed turn: `stop_reason:"tool_use"`, server search deferred until you return client results; user message must contain only `tool_result`s). |
| Search + image together | not documented either way | not documented either way | not documented either way (no restriction) |
| Search price | $0.007 (Exa), $0.001-0.005 (Parallel), $0.005 Perplexity, or native per-model `pricing.web_search` | $14/1000 queries (Gemini 3+), 5,000 free/mo | $10/1000 |
| Cheapest capable | `openai/gpt-5-nano` $0.05/$0.40 per M, $0.01/search [V-live] | `gemini-3.5-flash-lite` $0.30/$2.50 | `claude-haiku-5-5` $0.10/$0.50 |
| Domain filter / reddit.com | `allowed_domains`/`include_domains` (engine dependent; Google-native none) | none | `allowed_domains` (not with blocked) |

---------------------------------------------------------------------------
## 5. One shared format? Recommendation

- Shared OpenAI-style format: **OpenRouter** is the only one that is genuinely OpenAI-chat-completions-shaped AND has provider-run search with citations (annotations) AND tools + images + json_schema in one endpoint, for any underlying model (incl. Claude and Gemini models served via OpenRouter). Cost: user must have an OpenRouter key; a model's own native key is not used.
- Gemini compat endpoint: chat/tools/images/JSON work; no documented web search in chat completions. Claude compat endpoint: chat/tools/images/strict-json work; no web search, no citations, "not production-ready", `strict` tool flag ignored. So using compat endpoints loses search + citations (and thinking/caching/PDF); images and tools survive.
- Smallest design:
  1. **Ship now: ONE code path = OpenRouter chat completions.** It covers 100% of the five needs for any model.
  2. If native keys are required: **three paths total** (OpenRouter, Anthropic Messages, Gemini Interactions), because search only works natively on the latter two, and Gemini's/Anthropic's native bodies differ in tool/result/citation shapes. Hide them behind one internal turn result: `{text, citations[{url,title,start,end?}], tool_calls[{id,name,args(dict)}], raw_assistant_message}` and one `send_tool_results(results)`.
  3. Do NOT do "OpenAI-compat for Gemini/Claude + separate search API" — it adds a path (search as function) without saving the native paths' complexity. Keep the search-as-function workaround only as a fallback for Gemini <3 models.
- Always run JSON extraction (recipe -> schema.org, nutrition estimate) as its own request without tools/search (avoids three unverified combos), and do search turns separately from extraction.
- Always run the tool loop yourself with a cap (e.g. 6 iterations); stop immediately when the response contains a proposal tool call.

---------------------------------------------------------------------------
## 6. Not verified / what a live test with real keys must confirm

OpenRouter
1. `openrouter:web_search` inside `/chat/completions` `tools` next to function tools: request accepted, search happens, only user-function calls surface in `tool_calls`, annotations appear on `message.annotations` (field names in section 1.6 are from the plugin page).
2. `max_tool_calls` / `max_uses` behavior on chat completions; whether `parameters.allowed_domains:["reddit.com"]` returns reddit results on Exa/Parallel (docs silent on indexing).
3. Search + image in one request; json_schema + tools/search together.
4. Exact error text/status for model without tools/vision; any size limit on base64 images; `start_index` units.
5. The negative-price router rows and `:nitro/:floor` suffix behavior (not read).

Gemini
6. Whether `Api-Revision` is still required or ignored today (docs: ignored after Jun 8 2026); Interactions error JSON shape and which of the two doc error tables is right (invalid key 401 vs 400).
7. Search + function mixing on `gemini-3.5-flash-lite` specifically; need for `tool_choice:"validated"`; answering multiple `function_call` steps; stateless history payload; what happens to an unanswered `requires_action` interaction (proposal tools).
8. Legacy `generateContent` shapes and the older "no search + function calling" restriction (no page loaded; nothing invented).
9. Search + image together; `search_suggestions` display requirement; any way to bias to reddit.com.
10. Capability-discovery field for Gemini models (none verified).

Claude
11. `anthropic-version: 2026-10-21` vs `2023-06-01` acceptance for BYO-key users; `disable_parallel_tool_use` field (page not read); exact message for image/tool unsupported model; "credit balance too low" mapping to 402 vs 400.
12. Web search + structured output / strict tools in one request; web search + image in one request; whether `reddit.com` returns results under `allowed_domains`.
13. Models API `capabilities` field names for image input / tools (only `server_tools.web_search.supported` confirmed).

General
14. Streaming with tools (all three): not researched beyond one-line notes. Non-streaming is simplest and sufficient: one POST, parse JSON, loop on tool calls. Streaming complicates tool use because function-call arguments arrive as partial JSON deltas that must be accumulated (Claude `input_json_delta`, Gemini argument deltas, OpenAI `tool_calls[].function.arguments` chunks) and search events add a pause mid-stream. [Claude streaming shape V; others NV]
15. All prices/model ids are as of 2026-11-09 and change; read OpenRouter `/models` at runtime.

Sources fetched: openrouter.ai/docs (server-tools, server-tools/web-search, plugins/web-search, tool-calling, structured-outputs, app-attribution, api-reference/errors, api/api-reference chat + models .md, image-understanding), openrouter.ai/api/v1/models (live JSON); aistudio.google.com/docs (google-search, tool-combination, function-calling, interactions, interactions-breaking-changes-may-2026, image-understanding, structured-output, openai, pricing, troubleshooting, api-errors, api-reference/interactions-api); platform.claude.com/docs (web-search-tool, server-tools, define-tools, handle-tool-calls, structured-outputs, vision, api/errors, api/versioning, models/overview, about-claude/pricing, cli-sdks-libraries/libraries/openai-sdk).
