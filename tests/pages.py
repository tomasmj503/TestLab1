"""Ayudas para las pruebas: HTML falso con la misma forma que books.toscrape.com y catálogos armados a mano."""
from decimal import Decimal
from html import escape
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from app.catalog import Catalog, Category, normalize
from app.scraper import ListedBook

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_soup(name: str) -> BeautifulSoup:
    return BeautifulSoup((FIXTURES / name).read_bytes(), "html.parser", from_encoding="utf-8")


def listing_html(books: list[tuple[str, str, str]], next_href: str | None = None) -> str:
    """books: [(título completo, href relativo, precio como "23.21")]. El texto visible va cortado, como en el sitio."""
    pods = "".join(
        f'<article class="product_pod"><h3><a href="{href}" title="{escape(title)}">{escape(title[:10])}...</a></h3>'
        f'<div class="product_price"><p class="price_color">£{price}</p></div></article>'
        for title, href, price in books
    )
    pager = f'<ul class="pager"><li class="next"><a href="{next_href}">next</a></li></ul>' if next_href else ""
    return f"<html><body><ol class='row'>{pods}</ol>{pager}</body></html>"


def home_html(categories: list[tuple[str, str]]) -> str:
    items = "".join(f'<li><a href="{href}">\n  {name}\n</a></li>' for name, href in categories)
    return (
        '<html><body><div class="side_categories"><ul class="nav nav-list"><li>'
        f'<a href="catalogue/category/books_1/index.html">Books</a><ul>{items}</ul></li></ul></div></body></html>'
    )


def book(title: str, price: str, url: str = "") -> ListedBook:
    return ListedBook(title=title, url=url or f"https://books.example/{normalize(title)}", price_gbp=Decimal(price))


def make_catalog(categories: dict[str, list[ListedBook]]) -> Catalog:
    cats = {normalize(name): Category(name=name, books=tuple(books)) for name, books in categories.items()}
    books: dict[str, ListedBook] = {}
    for category in cats.values():
        for item in category.books:
            books.setdefault(normalize(item.title), item)
    return Catalog(books=books, categories=cats)


def fake_fetch(pages: dict[str, str]):
    """Sustituto de scraper.fetch_html: sirve HTML de un diccionario; una URL que no está simula web caída."""

    def fetch(session: requests.Session, url: str) -> BeautifulSoup:
        if url not in pages:
            raise requests.ConnectionError(f"sin respuesta: {url}")
        return BeautifulSoup(pages[url], "html.parser")

    return fetch
