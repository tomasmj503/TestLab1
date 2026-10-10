import time
from decimal import Decimal

import pytest
import requests
from fastapi.testclient import TestClient

from app import scraper
from app.catalog import CatalogStore
from app.main import create_app
from app.scraper import BookDetail, ScrapeError
from tests.pages import book, make_catalog

TOKEN = "token-de-prueba"
AUTH = {"X-Eval-Token": TOKEN}

CATALOG = make_catalog(
    {
        "Travel": [
            book("The Road to Little Dribbling", "23.21"),
            book("Second Travel", "26.08"),
            book("Third Travel", "30.54"),
            book("Vagabonding", "36.94"),
        ],
        "Default": [book("First Cheap", "10.23"), book("Second Cheap", "10.23"), book("Pricey", "50.00")],
        "Empty": [],
    }
)


@pytest.fixture
def client() -> TestClient:
    store = CatalogStore(loader=lambda: CATALOG)
    store.reload()
    return TestClient(create_app(token=TOKEN, store=store))


def run(client: TestClient, case_type: str, params: dict, headers=AUTH, case_id: str = "t"):
    return client.post("/run", json={"case_id": case_id, "type": case_type, "params": params}, headers=headers)


# ---- /health y autenticación ------------------------------------------------------------

def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"X-Eval-Token": "otro"}, {"X-Eval-Token": ""}])
def test_run_without_valid_token_is_401(client, headers):
    response = run(client, "mas_barato", {"category": "Travel"}, headers=headers)
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_auth_is_checked_before_body(client):
    response = client.post("/run", content="{roto", headers={"X-Eval-Token": "otro"})
    assert response.status_code == 401


# ---- 400 bad_request --------------------------------------------------------------------

@pytest.mark.parametrize(
    "body",
    [
        {"type": "mas_barato", "params": {"category": "Travel"}},  # falta case_id
        {"case_id": "x", "params": {"category": "Travel"}},  # falta type
        {"case_id": "x", "type": "mas_barato"},  # falta params
        {"case_id": "x", "type": "mas_barato", "params": "Travel"},  # params no es objeto
        {"case_id": "x", "type": 5, "params": {}},  # type no es texto
        ["no", "es", "objeto"],
    ],
)
def test_missing_or_malformed_fields_are_400(client, body):
    response = client.post("/run", json=body, headers=AUTH)
    assert response.status_code == 400
    assert response.json() == {"error": "bad_request"}


def test_broken_json_is_400(client):
    response = client.post("/run", content='{"case_id": "x", ', headers={**AUTH, "Content-Type": "application/json"})
    assert response.status_code == 400
    assert response.json() == {"error": "bad_request"}


def test_empty_body_is_400(client):
    assert client.post("/run", headers=AUTH).status_code == 400


# ---- contrato de respuesta --------------------------------------------------------------

def test_response_has_contract_fields(client):
    body = run(client, "mas_barato", {"category": "Travel"}, case_id="pub-03").json()
    assert set(body) == {"case_id", "status", "answer", "cost_usd", "elapsed_ms"}
    assert body["case_id"] == "pub-03"
    assert body["cost_usd"] == 0
    assert isinstance(body["elapsed_ms"], int)


def test_unknown_type_is_200_with_status_error(client):
    response = run(client, "tipo_inventado", {"title": "x"})
    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert response.json()["answer"] == {}


# ---- precio_libro -----------------------------------------------------------------------

def test_precio_libro_ok_reads_book_page(client, monkeypatch):
    seen = []

    def fake_detail(url: str) -> BookDetail:
        seen.append(url)
        return BookDetail(price_gbp=Decimal("23.21"), stock=7)

    monkeypatch.setattr(scraper, "fetch_book_detail", fake_detail)
    body = run(client, "precio_libro", {"title": "the road to little dribbling"}).json()
    assert body["status"] == "ok"
    assert body["answer"] == {"price_gbp": 23.21, "stock": 7}
    assert len(seen) == 1  # una sola petición a la página del libro


def test_precio_libro_not_found_does_not_touch_the_web(client, monkeypatch):
    def boom(url: str) -> BookDetail:
        raise AssertionError("no debía pedir ninguna página")

    monkeypatch.setattr(scraper, "fetch_book_detail", boom)
    body = run(client, "precio_libro", {"title": "Libro que no existe"}).json()
    assert body["status"] == "not_found"
    assert body["answer"] == {}


@pytest.mark.parametrize("failure", [requests.Timeout("lento"), requests.ConnectionError("caída"), ScrapeError("raro")])
def test_precio_libro_web_failure_is_status_error_not_http_500(client, monkeypatch, failure):
    def fail(url: str) -> BookDetail:
        raise failure

    monkeypatch.setattr(scraper, "fetch_book_detail", fail)
    response = run(client, "precio_libro", {"title": "Vagabonding"})
    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert response.json()["answer"] == {}


def test_precio_libro_missing_title_is_status_error(client):
    assert run(client, "precio_libro", {}).json()["status"] == "error"


# ---- contar_categoria -------------------------------------------------------------------

@pytest.mark.parametrize(
    ("limit", "expected"),
    [
        (30, 2),  # 30.54 queda fuera
        (36.94, 4),  # tope exacto: se incluye (<=)
        (36.93, 3),
        (20.0, 0),
        (100, 4),
    ],
)
def test_contar_categoria_is_inclusive(client, limit, expected):
    body = run(client, "contar_categoria", {"category": "travel", "max_price_gbp": limit}).json()
    assert body["status"] == "ok"
    assert body["answer"] == {"count": expected}


def test_contar_categoria_unknown_category_is_not_found(client):
    body = run(client, "contar_categoria", {"category": "CategoriaFalsa", "max_price_gbp": 30}).json()
    assert body["status"] == "not_found"
    assert body["answer"] == {}


@pytest.mark.parametrize("limit", ["30", None, True])
def test_contar_categoria_bad_limit_is_status_error(client, limit):
    body = run(client, "contar_categoria", {"category": "Travel", "max_price_gbp": limit}).json()
    assert body["status"] == "error"


def test_contar_categoria_nan_limit_is_status_error(client):
    # NaN no es JSON estricto, pero Python lo acepta al leer: se manda como texto crudo.
    raw = '{"case_id": "t", "type": "contar_categoria", "params": {"category": "Travel", "max_price_gbp": NaN}}'
    response = client.post("/run", content=raw, headers={**AUTH, "Content-Type": "application/json"})
    assert response.status_code == 200
    assert response.json()["status"] == "error"


# ---- mas_barato -------------------------------------------------------------------------

def test_mas_barato(client):
    body = run(client, "mas_barato", {"category": "Travel"}).json()
    assert body["status"] == "ok"
    assert body["answer"] == {"title": "The Road to Little Dribbling", "price_gbp": 23.21}


def test_mas_barato_tie_returns_first_in_site_order(client):
    body = run(client, "mas_barato", {"category": "Default"}).json()
    assert body["answer"] == {"title": "First Cheap", "price_gbp": 10.23}


def test_mas_barato_unknown_or_empty_category_is_not_found(client):
    assert run(client, "mas_barato", {"category": "Nope"}).json()["status"] == "not_found"
    assert run(client, "mas_barato", {"category": "Empty"}).json()["status"] == "not_found"


# ---- catálogo, precarga y /reload -------------------------------------------------------

def test_catalog_never_loaded_answers_status_error():
    app = create_app(token=TOKEN, store=CatalogStore(loader=lambda: CATALOG))  # sin precargar
    body = run(TestClient(app), "mas_barato", {"category": "Travel"}).json()
    assert body["status"] == "error"


def test_reload_requires_token_and_reports_counts(client):
    assert client.post("/reload").status_code == 401
    response = client.post("/reload", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["books"] == 7
    assert response.json()["categories"] == 3


def test_failed_manual_reload_is_502_and_keeps_catalog():
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        if calls["n"] > 1:
            raise requests.ConnectionError("web caída")
        return CATALOG

    store = CatalogStore(loader=loader)
    store.reload()
    client = TestClient(create_app(token=TOKEN, store=store))
    assert client.post("/reload", headers=AUTH).status_code == 502
    assert run(client, "mas_barato", {"category": "Travel"}).json()["status"] == "ok"


def test_startup_preloads_and_refreshes_periodically():
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return CATALOG

    store = CatalogStore(loader=loader)
    app = create_app(token=TOKEN, store=store, refresh_interval_s=0.05)
    with TestClient(app) as client:
        assert calls["n"] >= 1  # precarga ya hecha cuando arranca
        assert run(client, "mas_barato", {"category": "Travel"}).json()["status"] == "ok"
        time.sleep(0.4)
        assert calls["n"] >= 3  # y se vuelve a recargar sola


def test_startup_survives_failed_preload():
    def loader():
        raise requests.ConnectionError("web caída al arrancar")

    app = create_app(token=TOKEN, store=CatalogStore(loader=loader))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert run(client, "mas_barato", {"category": "Travel"}).json()["status"] == "error"


def test_startup_without_any_token_refuses_to_start(monkeypatch, tmp_path):
    monkeypatch.delenv("EVAL_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)  # sin .env a la vista
    app = create_app(store=CatalogStore(loader=lambda: CATALOG))
    with pytest.raises(RuntimeError, match="EVAL_TOKEN"), TestClient(app):
        pass
