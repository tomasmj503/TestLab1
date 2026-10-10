import logging
from decimal import Decimal

import pytest
import requests

from app import scraper
from app.catalog import CatalogStore, load_catalog
from tests.pages import book, fake_fetch, home_html, listing_html, make_catalog

BASE = scraper.BASE_URL
TRAVEL = BASE + "catalogue/category/books/travel_2/index.html"
TRAVEL_P2 = BASE + "catalogue/category/books/travel_2/page-2.html"
MYSTERY = BASE + "catalogue/category/books/mystery_3/index.html"


def _site(**overrides: str) -> dict[str, str]:
    pages = {
        BASE: home_html(
            [("Travel", "catalogue/category/books/travel_2/index.html"),
             ("Mystery", "catalogue/category/books/mystery_3/index.html")]
        ),
        TRAVEL: listing_html([("Vagabonding", "../../../vag_1/index.html", "36.94")], next_href="page-2.html"),
        TRAVEL_P2: listing_html([("It's Only the Himalayas", "../../../him_2/index.html", "45.17")]),
        MYSTERY: listing_html([("Sharp Objects", "../../../sharp_3/index.html", "47.82")]),
    }
    pages.update(overrides)
    return pages


def test_load_catalog_walks_every_category_and_page(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_html", fake_fetch(_site()))
    loaded = load_catalog()
    assert len(loaded.books) == 3
    assert [b.title for b in loaded.categories["travel"].books] == ["Vagabonding", "It's Only the Himalayas"]
    assert loaded.load_seconds >= 0


def test_lookup_tolerates_writing_variations(monkeypatch):
    monkeypatch.setattr(scraper, "fetch_html", fake_fetch(_site()))
    loaded = load_catalog()
    found = loaded.find_book("its only the himalayas")
    assert found is not None and found.title == "It's Only the Himalayas"
    assert loaded.find_category("  TRAVEL ") is not None
    assert loaded.find_book("Libro que no existe") is None
    assert loaded.find_category("CategoriaFalsa") is None


def test_duplicate_title_keeps_first_and_logs(monkeypatch, caplog):
    pages = _site(**{MYSTERY: listing_html([("Vagabonding", "../../../otro_9/index.html", "1.00")])})
    monkeypatch.setattr(scraper, "fetch_html", fake_fetch(pages))
    with caplog.at_level(logging.WARNING, logger="catalog"):
        loaded = load_catalog()
    found = loaded.find_book("Vagabonding")
    assert found is not None and found.price_gbp == Decimal("36.94")
    assert "duplicado" in caplog.text


def test_failed_category_fails_the_whole_load(monkeypatch):
    pages = _site()
    del pages[MYSTERY]
    monkeypatch.setattr(scraper, "fetch_html", fake_fetch(pages))
    with pytest.raises(requests.ConnectionError):
        load_catalog()


def test_failed_reload_keeps_previous_catalog():
    good = make_catalog({"Travel": [book("Vagabonding", "36.94")]})
    results = [good, RuntimeError("web caída")]

    def loader():
        item = results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    store = CatalogStore(loader=loader)
    assert store.reload() is good
    with pytest.raises(RuntimeError):
        store.reload()
    assert store.catalog is good
