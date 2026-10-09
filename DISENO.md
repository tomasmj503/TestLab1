# DISENO.md — Reto 1: El agente que opera lo que no tiene API

## Problema
Extraer precio, stock y conteos de books.toscrape.com respondiendo en < 30 s via API REST con autenticación por token.

## Hallazgos del sitio (observación directa)
- No hay buscador ni filtros de precio: toda la lógica de filtrado la hace nuestro sistema.
- Los títulos en la lista salen cortados; el título completo solo está dentro de la página del libro.
- El stock exacto (`In stock (19 available)`) solo aparece dentro de la página del libro, no en la lista.
- Algunas categorías tienen varias páginas (botón "next"): hay que recorrerlas todas.
- El carrito no es útil para ningún caso: queda fuera del scope.

## Supuestos
- El sitio es estático durante el evento: cachear al arrancar es válido.
- Los organizadores pueden escribir títulos/categorías con variaciones menores de escritura.
- El token `X-Eval-Token` lo proveen los organizadores; se guarda como variable de entorno.
- `max_price_gbp` es inclusivo (≤): un libro cuyo precio es exactamente el tope sí se cuenta.

## Casos difíciles
| Caso | Riesgo | Mitigación |
|---|---|---|
| Título con apóstrofe, acento o mayúscula | No coincide exacto | Normalización (ver D2) |
| Categoría con 3+ páginas | Lento si se recorre en caliente | Pre-carga al arrancar |
| Empate en `mas_barato` (mismo precio) | Resultado ambiguo | Devolver el primero en orden de aparición en el sitio |
| Título duplicado en catálogo | Resultado ambiguo | Devolver el primero encontrado; registrar en log |
| Categorías raras (`Default`, `Add a comment`) | Pueden confundirse con errores | Se tratan igual que cualquier categoría; si existe → responder |
| Web caída o lenta (incidente) | Request falla o supera 30 s | Timeout de 10 s por request; si falla → `"status":"error"`; catálogo en memoria se recarga solo cada 10 min y hay ruta `POST /reload` para forzarlo a mano |
| Libro/categoría que no existe | Devolver `error` en vez de `not_found` | Si no hay match tras normalizar → `"status":"not_found"` |

## Fuera de scope
- **Carrito y checkout**: ninguno de los 3 tipos de caso requiere comprar.
- **Login**: el sitio es público, no hay autenticación de usuario.
- **Imágenes, reseñas y ratings**: el brief no los pide; añadirlos solo agregaría tiempo de descarga.
- **Escritura de datos**: solo leemos el sitio, nunca modificamos nada.
- **Caché persistente entre reinicios**: no es necesario para un evento de un día; simplificar reduce errores.

---

## Arquitectura

```
Organizadores
     │  POST /run  (X-Eval-Token)
     ▼
┌──────────────────────────────────┐
│  FastAPI  (Docker, Contabo)      │
│                                  │
│  arranque → ScraperInit ────────►│──► books.toscrape.com (catálogo completo)
│  cada 10 min → recarga auto ────►│──► books.toscrape.com (actualiza memoria)
│                                  │
│  POST /run                       │
│    ├─ valida token → 401         │
│    ├─ valida body  → 400         │
│    └─ Router de tipos            │
│         ├─ precio_libro ────────►│── 1 request a página del libro (stock exacto)
│         ├─ contar_categoria ────►│── catálogo en memoria + filtro ≤ precio
│         └─ mas_barato ──────────►│── catálogo en memoria
│                                  │
│  GET  /health → {"status":"ok"}  │
│  POST /reload → recarga manual   │
└──────────────────────────────────┘
     │  Caddy (HTTPS)
     ▼
  URL pública estable
  (si Contabo falla → reiniciar contenedor con Docker restart policy)
```

**Al arrancar:** recorrer sidebar → por cada categoría, seguir "next" hasta el final → guardar en memoria `{ título_normalizado → url, categoría_normalizada → [libros] }`. Luego ya está listo para responder. Tiempo de pre-carga: estimado, por medir.

---

## Decisiones

### D1 — Cómo lee el sistema las páginas web
**Elegida: leer el HTML directamente (librería `requests` + `BeautifulSoup`).**
- Descartado: **Playwright (navegador automatizado)**. Lanza un Chrome real: más lento (estimado, por medir: ~2-5 s por página vs ~0.5 s con requests directos), más memoria, más puntos de falla. El sitio no usa JavaScript dinámico, así que es innecesario.
- Descartado: **Agente de IA que navega**. Un modelo de lenguaje decide qué clicar y leer. Útil cuando el sitio cambia impredeciblemente o la lógica es muy compleja; aquí la estructura es fija y conocida. Añade costo en tokens y latencia extra por paso (estimado, por medir: ~2-10 s por acción). Lo usaríamos si hubiera que interpretar texto ambiguo o tomar decisiones no programables.

### D2 — Cómo comparar títulos y categorías
**Elegida: normalización (minúsculas + quitar tildes, puntuación y espacios extra).**
- Descartada: **comparación exacta**. Falla ante cualquier variación de escritura; el brief lo advierte explícitamente.
- Descartada: **IA para comparar**. Maneja casos más complejos pero añade costo y latencia innecesarios cuando la normalización ya resuelve el problema. Medimos si es suficiente con los 10 casos de prueba propios (ver abajo); si alguno falla por variación no cubierta, añadimos regla específica.

### D3 — Cuándo cargar el catálogo
**Elegida: pre-cargar al arrancar el servidor (no al primer request).**
- Descartada: **cargar en el primer request**. Ese request tardaría > 30 s y se perdería el caso.
- Descartada: **cargar por demanda (categoría por categoría al recibir cada pregunta)**. Demasiado lento para categorías con varias páginas dentro del límite de 30 s.

### D4 — Infraestructura
**Elegida: Contabo propio (Docker + Caddy, siempre encendido). Si el proceso falla, Docker lo reinicia solo (`restart: always`).**
- Descartado: **Railway / Render (plan gratuito)**. Duermen la instancia tras inactividad; el arranque en frío puede superar 30 s (estimado, por medir; es comportamiento conocido del plan gratuito).
- Descartado: **Vercel como respaldo**. Las funciones serverless tienen límite de tiempo ajustado y tendrían que hacer la pre-carga del catálogo en frío, que es exactamente el problema que las descartó como opción principal. Una contradicción sin solución simple; es más seguro depender de Docker `restart: always`.

---

## Plan de medición

**14 casos de prueba propios antes de entregar** (resultados medidos en el sitio real el 2026-10-09):

| # | Tipo | Entrada | Resultado esperado (medido) |
|---|---|---|---|
| T01 | `precio_libro` | `"It's Only the Himalayas"` | `{"price_gbp": 45.17, "stock": 19}` |
| T02 | `precio_libro` | `"its only the himalayas"` (sin apóstrofe ni mayúsculas) | `{"price_gbp": 45.17, "stock": 19}` — normalización |
| T03 | `precio_libro` | `"Sharp Objects"` (libro distinto, evita valor hardcodeado) | `{"price_gbp": 47.82, "stock": 20}` |
| T04 | `precio_libro` | `"Libro que no existe"` | `status: "not_found", answer: {}` |
| T05 | `contar_categoria` | Travel, `max_price_gbp: 30` | `{"count": 2}` (£23.21 y £26.08; el £30.54 queda fuera) |
| T06 | `contar_categoria` | Travel, `max_price_gbp: 36.94` (precio exacto de Vagabonding) | `{"count": 4}` — confirma que el tope exacto sí se incluye (≤) |
| T07 | `contar_categoria` | Mystery, `max_price_gbp: 20.30` (precio exacto de Blood Defense) | `{"count": 11}` — 2 páginas, borde exacto incluido |
| T08 | `contar_categoria` | Travel, `max_price_gbp: 20.00` | `{"count": 0, "status": "ok"}` — categoría existe, ningún libro cumple |
| T09 | `contar_categoria` | `"CategoriaFalsa"` | `status: "not_found", answer: {}` |
| T10 | `mas_barato` | Travel | `{"title": "The Road to Little Dribbling: Adventures of an American in Britain (Notes From a Small Island #2)", "price_gbp": 23.21}` |
| T11 | `mas_barato` | Default — categoría rara con 8 páginas | `{"title": "Greek Mythic History", "price_gbp": 10.23}` |
| T12 | `precio_libro` | token incorrecto en cabecera | HTTP 401, `{"error": "unauthorized"}` |
| T13 | `precio_libro` | JSON con campo `params` faltante | HTTP 400, `{"error": "bad_request"}` |
| T14 | `precio_libro` | `type: "tipo_inventado"` | HTTP 200, `{"status": "error"}` |

**Métricas contables:**
- Aciertos: X / 14 (meta: 14/14 antes de entregar)
- Tiempo por caso: medir cada uno individualmente (meta: < 5 s estimado, por medir; límite duro: 30 s)
- `cost_usd` por caso: 0.00 (sin IA en scraping; si se añade IA en algún paso, medir por separado)
