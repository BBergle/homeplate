import json

import httpx
import pytest

from app import mealie

U = "https://x.com/r"
SCRAPE = ("POST", "/api/recipes/test-scrape-url")
IMPORT = ("POST", "/api/recipes/create/url")


@pytest.mark.parametrize("image,want", [
    ("https://i/a.jpg", "https://i/a.jpg"),
    ({"@type": "ImageObject", "url": "https://i/b.jpg"}, "https://i/b.jpg"),
    (["https://i/c.jpg", "https://i/d.jpg"], "https://i/c.jpg"),
    ([{"url": "https://i/e.jpg"}], "https://i/e.jpg"),
    (None, None),
])
def test_test_scrape_shapes(mock_mealie, image, want):
    mock_mealie[SCRAPE] = httpx.Response(200, json={"name": "Pie", "image": image, "recipeIngredient": ["x"] * 18})
    assert mealie.test_scrape("t", U) == {"name": "Pie", "image": want, "ingredients": 18}


def test_test_scrape_missing_fields(mock_mealie):
    mock_mealie[SCRAPE] = httpx.Response(200, json={})
    assert mealie.test_scrape("t", U) == {"name": None, "image": None, "ingredients": 0}


def test_test_scrape_refused_or_odd(mock_mealie):
    mock_mealie[SCRAPE] = httpx.Response(400, json={"detail": {"message": "BAD_RECIPE_DATA"}})
    assert mealie.test_scrape("t", U) is None
    mock_mealie[SCRAPE] = httpx.Response(200, json="nope")
    assert mealie.test_scrape("t", U) is None


def test_import_url(mock_mealie):
    seen = {}

    def handler(request):
        seen["body"], seen["auth"] = json.loads(request.content), request.headers["authorization"]
        return httpx.Response(201, json="the-slug")

    mock_mealie[IMPORT] = handler
    assert mealie.import_url("t", U) == "the-slug"
    assert seen == {"body": {"url": U, "includeTags": False}, "auth": "Bearer t"}
    mock_mealie[IMPORT] = httpx.Response(400, json={"detail": {"message": "BAD_RECIPE_DATA"}})
    with pytest.raises(mealie.MealieRejected):
        mealie.import_url("t", U)


def test_scrape_and_import_timeouts(mock_mealie):
    seen = []

    def handler(request):
        seen.append(request.extensions["timeout"]["read"])
        return httpx.Response(200, json={}) if request.url.path.endswith("test-scrape-url") else httpx.Response(201, json="s")

    mock_mealie[SCRAPE] = mock_mealie[IMPORT] = handler
    mealie.test_scrape("t", U)
    mealie.import_url("t", U)
    assert seen == [20, 60]
