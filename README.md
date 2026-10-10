# Reto 1 — El agente que opera lo que no tiene API

API que responde preguntas sobre la librería https://books.toscrape.com (precio y stock de un libro,
cuántos libros de una categoría cuestan hasta cierto precio, el libro más barato de una categoría).

- Contrato de la API: [BRIEF.md](BRIEF.md)
- Decisiones de diseño y plan de pruebas: [DISENO.md](DISENO.md)

## Cómo funciona (en corto)

1. **Al arrancar**, la API recorre las 50 categorías del sitio (todas sus páginas) y guarda el catálogo en memoria.
2. **Cada 10 minutos** lo recarga sola. `POST /reload` lo fuerza a mano. Si una recarga falla, se queda con el catálogo anterior.
3. **Cada pregunta** se contesta desde la memoria. Solo `precio_libro` hace 1 petición a la página del libro (el stock exacto solo está ahí).
4. Los títulos y categorías se comparan normalizados (sin mayúsculas, tildes ni puntuación): `its only the himalayas` encuentra `It's Only the Himalayas`.
5. No usa IA: `cost_usd` es siempre `0`.

## Rutas

| Ruta | Para qué | Token |
|---|---|---|
| `GET /health` | Responde `{"status":"ok"}` | no |
| `POST /run` | Resuelve un caso (ver BRIEF.md) | sí, cabecera `X-Eval-Token` |
| `POST /reload` | Recarga el catálogo ahora | sí, cabecera `X-Eval-Token` |

## Correrla en tu computador

Requiere Python 3.12.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

# El token va en el archivo .env (no se sube a git), una línea:
#   EVAL_TOKEN=el-token-que-entreguen-los-organizadores

.venv/bin/uvicorn app.main:app --port 8000
```

Al arrancar tarda unos segundos en cargar el catálogo; cuando aparece `Application startup complete` ya responde.
Si no hay `EVAL_TOKEN` (ni en el entorno ni en `.env`), la API se niega a arrancar.

Probar a mano:

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/run \
  -H "X-Eval-Token: $EVAL_TOKEN" -H "Content-Type: application/json" \
  -d '{"case_id":"pub-01","type":"precio_libro","params":{"title":"It'"'"'s Only the Himalayas"}}'
```

## Pruebas

```bash
.venv/bin/pytest -q          # 67 pruebas, sin internet
.venv/bin/ruff check .       # estilo
.venv/bin/pyright            # tipos
```

Los 14 casos del plan de medición de DISENO.md se corren contra la API viva con
`.claude/skills/verification-loop/run_cases.py` (necesita un archivo `.jsonl` con los casos y `EVAL_TOKEN` en el entorno).

## Docker

```bash
docker build -t reto1 .
docker run -d --restart always -p 8000:8000 -e EVAL_TOKEN=... reto1
```

La imagen escucha en `0.0.0.0:8000`. El token se pasa al arrancar; no queda dentro de la imagen.

## Resultados medidos (2026-10-09, API local contra el sitio real)

- Casos de DISENO.md: **14/14**.
- Precarga del catálogo: **3.8 s** (999 libros únicos, 50 categorías).
- Tiempo por caso: `precio_libro` ≈ 0.4 s (1 petición al sitio); `contar_categoria` y `mas_barato` < 0.01 s (memoria).
- `POST /reload`: 4.0 s.

## Límites conocidos

- **Errores de tipeo** en un título (letras cambiadas o faltantes) no se encuentran: la normalización solo cubre mayúsculas, tildes, puntuación y espacios. Daría `not_found`.
- **Título repetido en el sitio** ("The Star-Touched Queen" aparece 2 veces): se devuelve el primero y queda un aviso en el registro.
- **Si el sitio cambia su HTML**, las lecturas fallan y la API responde `status: "error"` (no se cae); el catálogo anterior sigue en memoria hasta que una recarga funcione.
- **Imagen Docker**: el `Dockerfile` está escrito pero no se pudo construir ni probar en la máquina de desarrollo (Docker apagado).
