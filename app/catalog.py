"""Catálogo en memoria: se precarga entero y se consulta sin tocar la web."""
import logging
import re
import threading
import time
import unicodedata
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app import scraper
from app.scraper import ListedBook, ScrapeError

log = logging.getLogger("catalog")

LOAD_WORKERS = 8  # categorías que se descargan a la vez durante la precarga

_APOSTROPHES = re.compile("['’‘`´]")
_NOT_WORD = re.compile(r"[\W_]+")


def normalize(text: str) -> str:
    """Minúsculas, sin tildes, sin puntuación y sin espacios de más (D2 de DISENO.md).

    "It's Only the Himalayas" y "its only   the himalayas" dan el mismo resultado.
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = _APOSTROPHES.sub("", text.casefold())  # "it's" -> "its", no "it s"
    text = text.replace("&", " and ")
    return " ".join(_NOT_WORD.sub(" ", text).split())


@dataclass(frozen=True)
class Category:
    name: str
    books: tuple[ListedBook, ...]  # en el orden en que aparecen en el sitio


@dataclass(frozen=True)
class Catalog:
    books: dict[str, ListedBook]  # título normalizado -> libro
    categories: dict[str, Category]  # nombre normalizado -> categoría
    load_seconds: float = 0.0

    def find_book(self, title: str) -> ListedBook | None:
        return self.books.get(normalize(title))

    def find_category(self, name: str) -> Category | None:
        return self.categories.get(normalize(name))


def _load_category(entry: tuple[str, str]) -> Category:
    name, url = entry
    session = scraper.make_session(retries=2)
    return Category(name=name, books=tuple(scraper.fetch_category_books(session, url)))


def load_catalog() -> Catalog:
    """Recorre la barra lateral y, por cada categoría, todas sus páginas."""
    started = time.perf_counter()
    home = scraper.fetch_html(scraper.make_session(retries=2), scraper.BASE_URL)
    entries = scraper.parse_categories(home, scraper.BASE_URL)
    if not entries:
        raise ScrapeError("no se encontraron categorías en la página de inicio")

    with ThreadPoolExecutor(max_workers=LOAD_WORKERS) as pool:
        loaded = list(pool.map(_load_category, entries))  # conserva el orden del sitio

    books: dict[str, ListedBook] = {}
    categories: dict[str, Category] = {}
    for category in loaded:
        categories.setdefault(normalize(category.name), category)
        for book in category.books:
            key = normalize(book.title)
            if key in books:
                log.warning("título duplicado, se conserva el primero: %r", book.title)
            else:
                books[key] = book
    if not books:
        raise ScrapeError("el catálogo quedó vacío")
    return Catalog(books=books, categories=categories, load_seconds=time.perf_counter() - started)


class CatalogStore:
    """Guarda el catálogo vigente. Una recarga fallida deja el anterior intacto."""

    def __init__(self, loader: Callable[[], Catalog] = load_catalog) -> None:
        self._loader = loader
        self._catalog: Catalog | None = None
        self._lock = threading.Lock()

    @property
    def catalog(self) -> Catalog | None:
        return self._catalog

    def reload(self) -> Catalog:
        with self._lock:  # una sola recarga a la vez
            catalog = self._loader()
            self._catalog = catalog  # se reemplaza de golpe: nunca queda a medias
            return catalog
