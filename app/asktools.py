import os
from urllib.parse import urlsplit

from app import mealie, webimg

DOWN = {"error": "the recipe library could not be reached"}

TOOLS = [
    {"type": "function", "function": {
        "name": "search_my_recipes",
        "description": "Search the person's own saved recipes by name or ingredient. Returns ids and names.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "get_recipe",
        "description": "Get one saved recipe's ingredients, steps and nutrition, by the id from search_my_recipes.",
        "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    }},
    {"type": "function", "function": {
        "name": "propose_recipes",
        "description": "Show the person recipes from the web as cards, each with an Add button. Call this whenever they ask you to find recipes. Use only pages you found by searching.",
        "parameters": {"type": "object", "properties": {
            "intro": {"type": "string", "description": "One short sentence shown above the cards."},
            "recipes": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"},
                "url": {"type": "string", "description": "The recipe page's full address."},
                "why": {"type": "string", "description": "One line on why it is a good pick."},
            }, "required": ["name", "url", "why"]}},
        }, "required": ["intro", "recipes"]},
    }},
]


def photos_dir() -> str:
    return os.path.join(os.environ.get("DATA_DIR", "/data"), "cards")


def _line(i) -> str:
    if not isinstance(i, dict):
        return ""
    return str(i.get("display") or i.get("note") or i.get("originalText") or "")


def lookup(name: str, args: dict, token: str) -> dict:
    try:
        if name == "search_my_recipes":
            hits = mealie.search_recipes(token, str(args.get("query", "")))[:8]
            return {"recipes": [{"id": h["id"], "name": h["name"]} for h in hits]}
        if name == "get_recipe":
            r = mealie.recipe(token, str(args.get("id", "")))
            n = r.get("nutrition") or {}
            return {
                "name": r.get("name"),
                "ingredients": [x[:500] for x in map(_line, r.get("recipeIngredient") or []) if x][:40],
                "steps": [str(s["text"])[:500] for s in r.get("recipeInstructions") or [] if isinstance(s, dict) and s.get("text")][:40],
                "calories": n.get("calories"),
                "protein": n.get("proteinContent"),
            }
    except (mealie.MealieError, mealie.MealieAuthError):
        return DOWN
    return {"error": "unknown tool"}


def recipe_cards(args: dict, token: str) -> tuple[str, list[dict]]:
    recipes = args.get("recipes")
    if not isinstance(recipes, list):
        return "", []
    intro = str(args.get("intro") or "").strip()[:300]
    cards, seen = [], set()
    for item in recipes:
        if len(cards) == 5:
            break
        if not isinstance(item, dict):
            continue
        url = webimg.public_https(str(item.get("url") or ""))
        if not url or url in seen:
            continue
        seen.add(url)
        # ponytail: pages are scraped one after another; parallelise if five cards feel slow
        scrape = mealie.test_scrape(token, url)
        host = (urlsplit(url).hostname or "").removeprefix("www.")
        scraped, given = (scrape or {}).get("name"), item.get("name")
        name = next((n.strip() for n in (scraped, given) if isinstance(n, str) and n.strip()), host)
        cards.append({
            "name": name[:120],
            "url": url,
            "host": host,
            "why": str(item.get("why") or "").strip()[:200],
            "importable": bool(scrape and scrape["ingredients"] > 0),
            "image": webimg.public_https(scrape["image"]) if scrape and scrape["image"] else None,
        })
    return intro, cards
