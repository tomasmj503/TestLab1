"""Lee books.toscrape.com: pide las páginas y extrae títulos, precios y stock.

No guarda estado; el catálogo en memoria vive en catalog.py.
"""
import re
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://books.toscrape.com/"
REQUEST_TIMEOUT_S = 10  # DISENO.md: timeout de 10 s por request
MAX_PAGES_PER_CATEGORY = 100  # freno por si el botón "next" diera vueltas en círculo

_PRICE = re.compile(r"\d+(?:\.\d+)?")
_STOCK = re.compile(r"\((\d+) available\)")


class ScrapeError(Exception):
    """La página llegó pero no tiene la forma esperada (el sitio cambió)."""


@dataclass(frozen=True)
class ListedBook:
    """Un libro tal como aparece en la lista de una categoría."""

    title: str  # completo: sale del atributo title del enlace, el texto visible viene cortado
    url: str
    price_gbp: Decimal


@dataclass(frozen=True)
class BookDetail:
    """Precio y stock leídos de la página del propio libro."""

    price_gbp: Decimal
    stock: int


def make_session(retries: int = 0) -> requests.Session:
    """Sesión HTTP; con retries > 0 reintenta errores 5xx y de conexión (solo para la precarga)."""
    session = requests.Session()
    if retries:
        retry = Retry(total=retries, backoff_factor=0.5, status_forcelist=(500, 502, 503, 504))
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def fetch_html(session: requests.Session, url: str) -> BeautifulSoup:
    response = session.get(url, timeout=REQUEST_TIMEOUT_S)
    response.raise_for_status()
    # El sitio es UTF-8 pero no lo declara en la cabecera: sin esto "£" llega como "Â£".
    return BeautifulSoup(response.content, "html.parser", from_encoding="utf-8")


def parse_price(text: str) -> Decimal:
    match = _PRICE.search(text)
    if match is None:
        raise ScrapeError(f"precio ilegible: {text!r}")
    return Decimal(match.group())


def parse_categories(soup: BeautifulSoup, page_url: str) -> list[tuple[str, str]]:
    """Devuelve [(nombre, url)] de la barra lateral, en el orden del sitio (sin el "Books" padre)."""
    return [
        (link.get_text(strip=True), urljoin(page_url, str(link["href"])))
        for link in soup.select("div.side_categories ul ul li a")
    ]


def parse_listing(soup: BeautifulSoup, page_url: str) -> tuple[list[ListedBook], str | None]:
    """Libros de una página de lista y la URL de la página siguiente (None si es la última)."""
    books: list[ListedBook] = []
    for pod in soup.select("article.product_pod"):
        link = pod.select_one("h3 a")
        price = pod.select_one("p.price_color")
        title = link.get("title") if link else None
        if link is None or price is None or not title:
            raise ScrapeError(f"libro con forma inesperada en {page_url}")
        books.append(
            ListedBook(
                title=str(title),
                url=urljoin(page_url, str(link["href"])),
                price_gbp=parse_price(price.get_text()),
            )
        )
    next_link = soup.select_one("li.next a")
    next_url = urljoin(page_url, str(next_link["href"])) if next_link else None
    return books, next_url


def parse_book_page(soup: BeautifulSoup) -> BookDetail:
    # Se lee solo la caja principal: más abajo la página lista libros recomendados con otros precios.
    main = soup.select_one("div.product_main")
    price = main.select_one("p.price_color") if main else None
    availability = main.select_one("p.availability") if main else None
    if price is None or availability is None:
        raise ScrapeError("página de libro con forma inesperada")
    match = _STOCK.search(availability.get_text())
    return BookDetail(price_gbp=parse_price(price.get_text()), stock=int(match.group(1)) if match else 0)


def fetch_category_books(session: requests.Session, category_url: str) -> list[ListedBook]:
    """Todos los libros de una categoría, siguiendo "next" hasta la última página."""
    books: list[ListedBook] = []
    url: str | None = category_url
    for _ in range(MAX_PAGES_PER_CATEGORY):
        if url is None:
            return books
        page_books, url = parse_listing(fetch_html(session, url), url)
        books.extend(page_books)
    raise ScrapeError(f"más de {MAX_PAGES_PER_CATEGORY} páginas en {category_url}")


def fetch_book_detail(url: str) -> BookDetail:
    """1 request a la página del libro: precio y stock exacto al momento de la consulta."""
    return parse_book_page(fetch_html(make_session(), url))
