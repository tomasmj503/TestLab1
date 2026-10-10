"""Catálogo en memoria: se precarga entero y se consulta sin tocar la web."""
import difflib
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

# Emparejado aproximado de títulos (D2 de DISENO.md). Valores elegidos midiendo sobre el catálogo real.
FUZZY_MIN_SCORE = 0.85  # parecido mínimo de letras (0 a 1) para aceptar un título con tipeos
FUZZY_MIN_MARGIN = 0.03  # ventaja mínima sobre el segundo mejor; si dos libros casi empatan => not_found
FUZZY_MIN_CHARS = 8  # consultas más cortas no se comparan por parecido: serían demasiado ambiguas
_TRUNCATION_MARKS = ("...", "…")  # cómo el sitio muestra un título recortado

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
        """Busca un libro por título, de lo más seguro a lo más flexible.

        1. Exacto tras normalizar.
        2. Inicio único: "A Light in the ..." -> "A Light in the Attic". Solo si el texto termina en
           "..." o tiene 2 palabras o más; una palabra suelta ("Sharp") es demasiado ambigua.
           Si el inicio lo comparten varios libros, responde None (no adivina).
        3. Parecido de letras, para tipeos: exige puntaje mínimo y ventaja sobre el segundo mejor.
        """
        key = normalize(title)
        if not key:
            return None
        if key in self.books:
            return self.books[key]

        truncated = title.rstrip().endswith(_TRUNCATION_MARKS)
        if not truncated and len(key.split()) < 2:
            return None

        starts = [candidate for candidate in self.books if candidate.startswith(key + " ")]
        if len(starts) == 1:
            return self.books[starts[0]]
        if starts or len(key) < FUZZY_MIN_CHARS:
            return None  # inicio compartido por varios libros, o consulta demasiado corta

        return self._closest(key)

    def _closest(self, key: str) -> ListedBook | None:
        floor = FUZZY_MIN_SCORE - FUZZY_MIN_MARGIN  # por debajo de esto no puede afectar la decisión
        matcher = difflib.SequenceMatcher(autojunk=False)
        matcher.set_seq2(key)
        best_key: str | None = None
        best = second = 0.0
        for candidate in self.books:
            matcher.set_seq1(candidate)
            if matcher.real_quick_ratio() < floor or matcher.quick_ratio() < floor:
                continue  # descarte rápido: estos dos cálculos son cotas superiores baratas
            score = matcher.ratio()
            if score > best:
                best_key, best, second = candidate, score, best
            elif score > second:
                second = score
        if best_key is None or best < FUZZY_MIN_SCORE or best - second < FUZZY_MIN_MARGIN:
            return None
        log.info("título aproximado: %r -> %r (parecido %.2f, ventaja %.2f)", key, best_key, best, best - second)
        return self.books[best_key]

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
