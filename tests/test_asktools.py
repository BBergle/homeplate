import httpx
import pytest

from app import asktools, mealie, webimg

SEARCH = ("GET", "/api/recipes")
SCRAPE = ("POST", "/api/recipes/test-scrape-url")


@pytest.fixture(autouse=True)
def fake_web(monkeypatch):
    monkeypatch.setattr(webimg, "public_https", lambda u: u if u.startswith("https://") and u.split("/")[2].removeprefix("www.").endswith(".example") else None)
    monkeypatch.setattr(webimg, "thumbnail", lambda u: None)


def test_lookup_search_and_get(mock_mealie):
    mock_mealie[SEARCH] = httpx.Response(200, json={"items": [{"id": f"i{n}", "name": f"R{n}", "slug": f"r{n}"} for n in range(9)]})
    out = asktools.lookup("search_my_recipes", {"query": "x"}, "t")
    assert len(out["recipes"]) == 8 and out["recipes"][0] == {"id": "i0", "name": "R0"}
    mock_mealie[("GET", "/api/recipes/i0")] = httpx.Response(200, json={
        "name": "R0",
        "recipeIngredient": [{"display": "1 cup flour"}, {"note": "salt"}] + [{"display": "x"}] * 50,
        "recipeInstructions": [{"text": "Mix."}] * 45,
        "nutrition": {"calories": "300", "proteinContent": None},
    })
    r = asktools.lookup("get_recipe", {"id": "i0"}, "t")
    assert r["name"] == "R0" and r["ingredients"][:2] == ["1 cup flour", "salt"]
    assert len(r["ingredients"]) == 40 and len(r["steps"]) == 40
    assert (r["calories"], r["protein"]) == ("300", None)


def test_lookup_unknown_and_mealie_down(mock_mealie):
    assert asktools.lookup("nope", {}, "t") == {"error": "unknown tool"}
    mock_mealie[SEARCH] = httpx.Response(500)
    assert asktools.lookup("search_my_recipes", {"query": "x"}, "t") == {"error": "the recipe library could not be reached"}


def test_recipe_cards(mock_mealie):
    def scrape(request):
        url = request.content.decode()
        if "refused" in url:
            return httpx.Response(400, json={})
        if "empty" in url:
            return httpx.Response(200, json={"name": "Empty", "recipeIngredient": []})
        return httpx.Response(200, json={"name": "Scraped " + url[-8:-2], "image": "https://img.example/p.jpg", "recipeIngredient": ["a"]})

    mock_mealie[SCRAPE] = scrape
    ex = lambda n: f"https://www.{n}.example/r"
    recipes = [
        {"name": "Private", "url": "https://10.0.0.1/r", "why": "w"},
        {"name": "One", "url": ex("one"), "why": "w" * 300},
        {"name": "Repeat", "url": ex("one"), "why": "w"},
        {"name": "Mine", "url": ex("refused"), "why": "w"},
        {"name": "Empty model", "url": ex("empty"), "why": "w"},
        {"name": "Three", "url": ex("three"), "why": "w"},
        {"name": "Four", "url": ex("four"), "why": "w"},
        {"name": "Five", "url": ex("five"), "why": "w"},
    ]
    intro, cards = asktools.recipe_cards({"intro": "  " + "i" * 400, "recipes": recipes}, "t")
    assert intro == "i" * 300 and len(cards) == 5
    assert [c["url"] for c in cards] == [ex(n) for n in ("one", "refused", "empty", "three", "four")]
    assert len(cards[0]["why"]) == 200 and cards[0]["host"] == "one.example" and cards[0]["importable"] is True
    assert cards[0]["image"] == "https://img.example/p.jpg"
    assert (cards[1]["name"], cards[1]["importable"], cards[1]["image"]) == ("Mine", False, None)
    assert (cards[2]["name"], cards[2]["importable"]) == ("Empty", False)


def _raise(out):
    if isinstance(out, Exception):
        raise out
    return out


def _two(mock_mealie, second):
    mock_mealie[SCRAPE] = lambda r: httpx.Response(200, json={"name": "Good", "recipeIngredient": ["a"]}) if "good" in r.content.decode() else _raise(second)
    recipes = [{"name": "G", "url": "https://good.example/r", "why": "w"}, {"name": "Bad", "url": "https://bad.example/r", "why": "w"}]
    return asktools.recipe_cards({"intro": "i", "recipes": recipes}, "t")[1]


@pytest.mark.parametrize("second", [httpx.Response(500, json={}), httpx.ReadTimeout("slow"), httpx.Response(404, json={})])
def test_recipe_cards_one_bad_page_keeps_the_rest(mock_mealie, second):
    cards = _two(mock_mealie, second)
    assert [(c["name"], c["importable"]) for c in cards] == [("Good", True), ("Bad", False)]


def test_recipe_cards_mealie_down_raises(mock_mealie):
    with pytest.raises(mealie.MealieError):
        _two(mock_mealie, httpx.ConnectError("down"))


@pytest.mark.parametrize("args", [{}, {"recipes": "x"}, {"recipes": ["a", 1, None]}])
def test_recipe_cards_bad_args(mock_mealie, args):
    assert asktools.recipe_cards(args, "t")[1] == []
    assert asktools.recipe_cards(args, "t")[0] == ""


def test_recipe_cards_private_image_dropped(mock_mealie):
    mock_mealie[SCRAPE] = httpx.Response(200, json={"name": "P", "image": "https://10.0.0.1/i.jpg", "recipeIngredient": ["a"]})
    _, cards = asktools.recipe_cards({"recipes": [{"name": "P", "url": "https://a.example/r", "why": "w"}]}, "t")
    assert cards[0]["image"] is None


@pytest.mark.parametrize("scraped,given,want", [(["x"], "Given", "Given"), (None, "  ", "a.example"), (["x"], None, "a.example")])
def test_recipe_cards_odd_names(mock_mealie, scraped, given, want):
    mock_mealie[SCRAPE] = httpx.Response(200, json={"name": scraped, "recipeIngredient": ["a"]})
    _, cards = asktools.recipe_cards({"recipes": [{"name": given, "url": "https://www.a.example/r", "why": "w"}]}, "t")
    assert cards[0]["name"] == want


def test_get_recipe_cuts_long_text(mock_mealie):
    mock_mealie[("GET", "/api/recipes/i0")] = httpx.Response(200, json={
        "name": "R", "recipeIngredient": [{"display": "x" * 900}], "recipeInstructions": [{"text": "y" * 900}], "nutrition": {}})
    r = asktools.lookup("get_recipe", {"id": "i0"}, "t")
    assert len(r["ingredients"][0]) == 500 and len(r["steps"][0]) == 500


def test_lookup_non_string_args(mock_mealie):
    seen = []

    def search(request):
        seen.append(request.url.params["search"])
        return httpx.Response(200, json={"items": []})

    mock_mealie[SEARCH] = search
    mock_mealie[("GET", "/api/recipes/['a/b']")] = httpx.Response(404, json={})
    assert asktools.lookup("search_my_recipes", {"query": 5}, "t") == {"recipes": []} and seen == ["5"]
    assert asktools.lookup("get_recipe", {"id": ["a/b"]}, "t") == {"error": "the recipe library could not be reached"}
