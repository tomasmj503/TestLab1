# Simulacro Frontier — Brief Reto 1

## CONTRATO COMÚN

La API debe tener dos rutas:

### 1. GET /health
Responde `{"status":"ok"}` con código 200.

### 2. POST /run
Encabezado obligatorio: `X-Eval-Token: <token>` (lo entregan los organizadores al validar).
Si falta o está mal → **401** con `{"error":"unauthorized"}`.

Pedido:
```json
{
  "case_id": "pub-01",
  "type": "precio_libro",
  "params": { "title": "It's Only the Himalayas" }
}
```

Respuesta 200:
```json
{
  "case_id": "pub-01",
  "status": "ok",
  "answer": { },
  "cost_usd": 0.0012,
  "elapsed_ms": 3400
}
```

- `status`: `"ok"` | `"not_found"` | `"error"`
- `cost_usd`: lo gastado en modelos de IA en ese caso (puede ser 0)
- Falta `case_id`, `type` o `params`, o JSON roto → **400** `{"error":"bad_request"}`
- `type` desconocido → **200** con `"status":"error"`
- Límite: **30 segundos** por caso. Más = caso perdido.

---

## RETO 1 — "El agente que opera lo que no tiene API"

Una librería online sin API: **https://books.toscrape.com**. El agente la opera como una persona: navega categorías, abre libros, lee precios y stock.

### Tipos de caso

| type | params | answer |
|---|---|---|
| `precio_libro` | `{"title": str}` | `{"price_gbp": float, "stock": int}` |
| `contar_categoria` | `{"category": str, "max_price_gbp": float}` | `{"count": int}` |
| `mas_barato` | `{"category": str}` | `{"title": str, "price_gbp": float}` |

Si el libro o la categoría no existe → `"status":"not_found"`, `"answer": {}`.

### Ejemplos públicos

```
pub-01 precio_libro {"title":"It's Only the Himalayas"}
  → {"price_gbp":45.17,"stock":19}

pub-02 contar_categoria {"category":"Travel","max_price_gbp":30}
  → {"count":2}

pub-03 mas_barato {"category":"Travel"}
  → {"title":"The Road to Little Dribbling: Adventures of an American in Britain (Notes From a Small Island #2)","price_gbp":23.21}

pub-04 precio_libro {"title":"Libro que no existe"}
  → status "not_found"
```

El set oculto trae títulos escritos distinto, categorías con varias páginas y casos nuevos.

---

## Entregas (cierre 20:00 en el evento real)
- Repo público en GitHub
- Entrypoint (URL pública de la API)
- Video de 2 min
- Descripción
