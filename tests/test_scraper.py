from decimal import Decimal

import pytest
import requests

from app import scraper
from app.scraper import ScrapeError
from tests.pages import fake_fetch, fixture_soup, listing_html

HOME = "https://books.toscrape.com/index.html"
TRAVEL = "https://books.toscrape.com/catalogue/category/books/travel_2/index.html"


def test_categories_from_real_home_page():
    categories = scraper.parse_categories(fixture_soup("home.html"), HOME)
    names = [name for name, _ in categories]
    assert len(categories) == 50
    assert "Books" not in names  # el enlace padre no es una categoría
    assert categories[0] == ("Travel", "https://books.toscrape.com/catalogue/category/books/travel_2/index.html")
    assert {"Default", "Add a comment", "Mystery"} <= set(names)


def test_listing_from_real_category_page():
    books, next_url = scraper.parse_listing(fixture_soup("travel_category.html"), TRAVEL)
    assert next_url is None  # Travel cabe en una sola página
    assert len(books) == 11
    first = books[0]
    assert first.title == "It's Only the Himalayas"
    assert first.price_gbp == Decimal("45.17")
    assert first.url == "https://books.toscrape.com/catalogue/its-only-the-himalayas_981/index.html"


def test_listing_uses_full_title_not_the_truncated_text():
    books, _ = scraper.parse_listing(fixture_soup("travel_category.html"), TRAVEL)
    assert "Full Moon over Noah’s Ark: An Odyssey to Mount Ararat and Beyond" in [b.title for b in books]


def test_book_page_reads_main_box_not_recommended_books():
    detail = scraper.parse_book_page(fixture_soup("book_himalayas.html"))
    assert detail.price_gbp == Decimal("45.17")
    assert detail.stock == 19


def test_listing_next_link_is_resolved_against_current_page():
    soup = listing_html([("Uno", "../../../uno_1/index.html", "10.00")], next_href="page-2.html")
    from bs4 import BeautifulSoup

    _, next_url = scraper.parse_listing(BeautifulSoup(soup, "html.parser"), TRAVEL.replace("index", "page-1"))
    assert next_url == "https://books.toscrape.com/catalogue/category/books/travel_2/page-2.html"


@pytest.mark.parametrize("text", ["£51.77", "Â£51.77", " 51.77 "])
def test_parse_price_survives_encoding_noise(text):
    assert scraper.parse_price(text) == Decimal("51.77")


def test_parse_price_without_digits_raises():
    with pytest.raises(ScrapeError):
        scraper.parse_price("agotado")


def test_listing_with_unexpected_shape_raises():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup('<article class="product_pod"><h3>sin enlace</h3></article>', "html.parser")
    with pytest.raises(ScrapeError):
        scraper.parse_listing(soup, TRAVEL)


def test_fetch_category_books_follows_next_until_last_page(monkeypatch):
    base = "https://site.test/cat/"
    pages = {
        base + "index.html": listing_html([("A", "a.html", "1.00")], next_href="page-2.html"),
        base + "page-2.html": listing_html([("B", "b.html", "2.00")], next_href="page-3.html"),
        base + "page-3.html": listing_html([("C", "c.html", "3.00")]),
    }
    monkeypatch.setattr(scraper, "fetch_html", fake_fetch(pages))
    books = scraper.fetch_category_books(requests.Session(), base + "index.html")
    assert [b.title for b in books] == ["A", "B", "C"]


def test_fetch_category_books_stops_if_next_loops_forever(monkeypatch):
    url = "https://site.test/cat/index.html"
    pages = {url: listing_html([("A", "a.html", "1.00")], next_href="index.html")}
    monkeypatch.setattr(scraper, "fetch_html", fake_fetch(pages))
    with pytest.raises(ScrapeError):
        scraper.fetch_category_books(requests.Session(), url)
