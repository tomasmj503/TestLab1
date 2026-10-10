"""API FastAPI: /health, /run y /reload (contrato en BRIEF.md, decisiones en DISENO.md)."""
import asyncio
import contextlib
import json
import logging
import os
import secrets
import time
from collections.abc import AsyncIterator
from typing import Any

from dotenv import dotenv_values
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app import handlers
from app.catalog import CatalogStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")

TOKEN_HEADER = "X-Eval-Token"
REFRESH_INTERVAL_S = 600  # DISENO.md: el catálogo se recarga solo cada 10 min
RETRY_AFTER_FAILED_LOAD_S = 30  # mientras no haya catálogo, se reintenta más seguido


def load_token() -> str:
    """EVAL_TOKEN del entorno (Docker) o, en local, de la línea EVAL_TOKEN del archivo .env."""
    token = os.environ.get("EVAL_TOKEN") or dotenv_values(".env").get("EVAL_TOKEN")
    if not token:
        raise RuntimeError("Falta EVAL_TOKEN (variable de entorno o línea en .env)")
    return token


def _error(status_code: int, code: str) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status_code)


async def _refresh_forever(store: CatalogStore, interval_s: float) -> None:
    while True:
        await asyncio.sleep(interval_s if store.catalog else RETRY_AFTER_FAILED_LOAD_S)
        try:
            catalog = await asyncio.to_thread(store.reload)
            log.info("recarga automática: %d libros en %.1f s", len(catalog.books), catalog.load_seconds)
        except Exception:
            log.exception("recarga automática falló; se mantiene el catálogo anterior")


def create_app(
    token: str | None = None, store: CatalogStore | None = None, refresh_interval_s: float = REFRESH_INTERVAL_S
) -> FastAPI:
    store = store or CatalogStore()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if app.state.token is None:
            app.state.token = load_token()  # sin token no se arranca: mejor fallar que aceptar a cualquiera
        try:  # D3: precarga antes de recibir tráfico
            catalog = await asyncio.to_thread(store.reload)
            log.info("precarga lista: %d libros, %d categorías en %.1f s",
                     len(catalog.books), len(catalog.categories), catalog.load_seconds)
        except Exception:
            log.exception("la precarga falló; /run responderá status=error hasta que cargue")
        refresher = asyncio.create_task(_refresh_forever(store, refresh_interval_s))
        yield
        refresher.cancel()

    app = FastAPI(lifespan=lifespan, title="Reto 1 - books.toscrape.com")
    app.state.token = token

    def authorized(request: Request) -> bool:
        expected: str | None = app.state.token
        if not expected:
            return False
        provided = request.headers.get(TOKEN_HEADER, "")
        return secrets.compare_digest(provided.encode(), expected.encode())  # tiempo constante

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/run")
    async def run(request: Request) -> JSONResponse:
        if not authorized(request):
            return _error(401, "unauthorized")
        started = time.perf_counter()
        try:
            body: Any = json.loads(await request.body())
        except ValueError:
            return _error(400, "bad_request")
        if (
            not isinstance(body, dict)
            or body.get("case_id") is None
            or not isinstance(body.get("type"), str)
            or not isinstance(body.get("params"), dict)
        ):
            return _error(400, "bad_request")

        status, answer = await run_in_threadpool(
            handlers.run_case, body["type"], body["params"], store.catalog
        )
        return JSONResponse(
            {
                "case_id": body["case_id"],
                "status": status,
                "answer": answer,
                "cost_usd": 0.0,  # sin IA en este diseño
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
            }
        )

    @app.post("/reload")
    def reload(request: Request) -> JSONResponse:
        if not authorized(request):
            return _error(401, "unauthorized")
        try:
            catalog = store.reload()
        except Exception as exc:
            log.exception("recarga manual falló; se mantiene el catálogo anterior")
            return JSONResponse({"status": "error", "detail": type(exc).__name__}, status_code=502)
        return JSONResponse(
            {
                "status": "ok",
                "books": len(catalog.books),
                "categories": len(catalog.categories),
                "load_seconds": round(catalog.load_seconds, 2),
            }
        )

    return app


app = create_app()
