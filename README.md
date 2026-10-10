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
   Los títulos además toleran recortes y tipeos, sin IA: `A Light in the ...` encuentra `A Light in the Attic` (si solo un libro empieza así) y `Sharp Objcts` encuentra `Sharp Objects` (por parecido de letras, con salvaguardas para no confundir libros de una misma serie). Detalle y números en D2 de DISENO.md.
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
.venv/bin/pytest -q          # 92 pruebas, sin internet
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

Estado: la imagen se construyó y se ejecutó con Docker en el servidor de despliegue con el commit `bc2d7a3`
(construcción hecha por el autor; los 20 casos pasan contra la URL pública, ver "Resultados medidos").

## Resultados medidos (2026-10-09, API local contra el sitio real)

- Casos de DISENO.md: **14/14**, más los 6 casos I01–I06 de títulos recortados y con tipeos: **20/20** en total.
- Títulos con errores (1441 consultas sintéticas sobre el catálogo real): 1391 correctas, 0 con libro equivocado, 50 `not_found`.
- Precarga del catálogo: **3.8 s y 4.5 s** en dos arranques (999 libros únicos, 50 categorías).
- Tiempo por caso: `precio_libro` ≈ 0.4 s (1 petición al sitio); `contar_categoria` y `mas_barato` < 0.01 s (memoria).
- `POST /reload`: 4.0 s.
- **URL pública** (`https://frontier.jutilabs.com`, commit `bc2d7a3`, 2026-10-09): **20/20** casos, incluidos I01–I06.
  Tiempos medidos desde el cliente: entre 0.29 s y 12.16 s (los casos que no abren el sitio, 0.3-0.7 s típico);
  el servidor reportó 1-317 ms en todos. Una sola corrida.

## Límites conocidos

- **Títulos inventados muy parecidos a uno real** pueden devolver ese libro (ej. `gone cannie shapiro 1` devuelve `Good in Bed (Cannie Shapiro #1)`).
- **Tipeos de otra forma** (palabras en otro orden, abreviaturas, palabras faltantes) y **tipeos en títulos de una sola palabra** dan `not_found`. Los tipeos con los que se calibró son sintéticos, no los del set oculto.
- **Una palabra suelta sin "..."** (`Sharp`) no se completa: da `not_found`.
- **Título repetido en el sitio** ("The Star-Touched Queen" aparece 2 veces): se devuelve el primero y queda un aviso en el registro.
- **Si el sitio cambia su HTML**, las lecturas fallan y la API responde `status: "error"` (no se cae); el catálogo anterior sigue en memoria hasta que una recarga funcione.
- **Tiempos por la red pública con picos**: en la corrida pública hubo casos de 2 a 12 s medidos desde el cliente mientras el servidor reportaba menos de 320 ms. El límite de 30 s se cumplió en todos, pero el pico más alto (12.16 s) usa cerca de la mitad del margen y su causa no está identificada.
