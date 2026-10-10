"""Lógica de cada tipo de caso. Devuelve (status, answer) según el contrato de BRIEF.md."""
import logging
import math
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import requests

from app import scraper
from app.catalog import Catalog
from app.scraper import ScrapeError

log = logging.getLogger("handlers")

Result = tuple[str, dict[str, Any]]

OK = "ok"
NOT_FOUND = "not_found"
ERROR = "error"


def _text(params: dict[str, Any], key: str) -> str | None:
    value = params.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _number(params: dict[str, Any], key: str) -> Decimal | None:
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return Decimal(str(value))  # str() evita arrastrar el error binario de float (20.3 -> 20.300000000000000711)


def precio_libro(params: dict[str, Any], catalog: Catalog) -> Result:
    title = _text(params, "title")
    if title is None:
        return ERROR, {}
    book = catalog.find_book(title)
    if book is None:
        return NOT_FOUND, {}
    detail = scraper.fetch_book_detail(book.url)  # el stock exacto solo está en la página del libro
    return OK, {"price_gbp": float(detail.price_gbp), "stock": detail.stock}


def contar_categoria(params: dict[str, Any], catalog: Catalog) -> Result:
    name = _text(params, "category")
    limit = _number(params, "max_price_gbp")
    if name is None or limit is None:
        return ERROR, {}
    category = catalog.find_category(name)
    if category is None:
        return NOT_FOUND, {}
    # <= : un libro cuyo precio es exactamente el tope sí se cuenta (supuesto de DISENO.md).
    return OK, {"count": sum(1 for book in category.books if book.price_gbp <= limit)}


def mas_barato(params: dict[str, Any], catalog: Catalog) -> Result:
    name = _text(params, "category")
    if name is None:
        return ERROR, {}
    category = catalog.find_category(name)
    if category is None or not category.books:
        return NOT_FOUND, {}
    cheapest = min(category.books, key=lambda book: book.price_gbp)  # empate: gana el primero del sitio
    return OK, {"title": cheapest.title, "price_gbp": float(cheapest.price_gbp)}


HANDLERS: dict[str, Callable[[dict[str, Any], Catalog], Result]] = {
    "precio_libro": precio_libro,
    "contar_categoria": contar_categoria,
    "mas_barato": mas_barato,
}


def run_case(case_type: str, params: dict[str, Any], catalog: Catalog | None) -> Result:
    """Nunca lanza: cualquier falla (web caída, HTML raro, bug) sale como status "error"."""
    handler = HANDLERS.get(case_type)
    if handler is None or catalog is None:  # tipo desconocido, o catálogo que nunca llegó a cargarse
        return ERROR, {}
    try:
        return handler(params, catalog)
    except (requests.RequestException, ScrapeError) as exc:
        log.warning("falló la lectura del sitio en %s: %s", case_type, exc)
    except Exception:
        log.exception("error inesperado en %s", case_type)
    return ERROR, {}
