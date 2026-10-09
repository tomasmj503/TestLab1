---
name: cost-aware-llm-pipeline
description: Cost optimization patterns for OpenRouter — model routing from .env, budget tracking, retry logic, and prompt caching. Cost read from usage.cost in the response, never hardcoded. Use when building features that call LLM APIs and need to track spend against the hackathon budget.
metadata:
  origin: ECC (adapted for OpenRouter; model names and prices come from .env and API response, not hardcoded)
---

# Cost-Aware LLM Pipeline — OpenRouter

Patrones para controlar el gasto en LLM. El modelo lo eliges tú en `.env`; el costo real lo devuelve OpenRouter en cada llamada.

## Variables de entorno requeridas

```bash
# .env
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=<modelo para tareas complejas>        # lo eliges tú con el brief
OPENROUTER_MODEL_CHEAP=<modelo para tareas simples>    # opcional; si no se define, usa OPENROUTER_MODEL para todo
OPENROUTER_BUDGET_USD=5.00                             # tope total del evento (US$5 bloqueados para debrief)
```

> **Cómo elegir el modelo:** cuando tengas el brief, busca en openrouter.ai/models los precios del día, compara calidad/costo, y escribe el nombre exacto en `.env`. No hay precios hardcodeados aquí porque cambian.

---

## 1. Cliente OpenRouter

OpenRouter usa la misma interfaz que OpenAI. La diferencia es la URL base y el campo `cost` en la respuesta.

```python
import os
from openai import OpenAI

def get_client() -> OpenAI:
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )
```

---

## 2. Routing de modelo por complejidad

Usa el modelo barato para tareas simples y el caro para las complejas. Si no hay modelo barato definido en `.env`, usa siempre el principal.

```python
def select_model(text_length: int, item_count: int) -> str:
    """Elige el modelo según complejidad de la tarea."""
    model_main  = os.environ["OPENROUTER_MODEL"]
    model_cheap = os.environ.get("OPENROUTER_MODEL_CHEAP", model_main)

    # Umbrales orientativos; ajustar según observación real
    THRESHOLD_CHARS = 10_000
    THRESHOLD_ITEMS = 30

    if text_length >= THRESHOLD_CHARS or item_count >= THRESHOLD_ITEMS:
        return model_main   # tarea compleja
    return model_cheap      # tarea simple
```

---

## 3. Leer el costo real de la respuesta

OpenRouter incluye `cost` dentro del objeto `usage` de cada respuesta. Es el costo real en USD de esa llamada.

```python
def extract_cost(response) -> float:
    """Lee el costo real devuelto por OpenRouter en usage.cost."""
    usage = response.usage
    if usage is None:
        return 0.0
    # El SDK de OpenAI mapea campos extra en model_extra
    extra = getattr(usage, "model_extra", None) or {}
    return float(extra.get("cost", 0.0))
```

---

## 4. Registro de costos inmutable

Cada llamada devuelve un registro nuevo; nunca se modifica el estado anterior. Hace que el historial de gasto sea fácil de auditar.

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class CostRecord:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float          # leído de usage.cost, nunca calculado a mano

@dataclass(frozen=True, slots=True)
class CostTracker:
    budget_usd: float
    records: tuple[CostRecord, ...] = ()

    @classmethod
    def from_env(cls) -> "CostTracker":
        return cls(budget_usd=float(os.environ.get("OPENROUTER_BUDGET_USD", "5.0")))

    def add(self, record: CostRecord) -> "CostTracker":
        return CostTracker(budget_usd=self.budget_usd, records=(*self.records, record))

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.records)

    @property
    def over_budget(self) -> bool:
        return self.total_cost > self.budget_usd

    @property
    def remaining(self) -> float:
        return self.budget_usd - self.total_cost
```

---

## 5. Reintentos solo en errores transitorios

Solo se reintenta cuando el error es temporal (red, rate limit, servidor). Errores permanentes (autenticación, request mal formado) fallan de inmediato para no gastar más presupuesto.

```python
import time
from openai import APIConnectionError, RateLimitError, InternalServerError

_RETRYABLE = (APIConnectionError, RateLimitError, InternalServerError)
_MAX_RETRIES = 3

def call_with_retry(func, *, max_retries: int = _MAX_RETRIES):
    for attempt in range(max_retries):
        try:
            return func()
        except _RETRYABLE:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)   # espera 1 s, 2 s, 4 s
        # AuthenticationError, BadRequestError, etc. → se propagan sin reintentar
```

---

## 6. Caché de prompts largos

Si el system prompt tiene más de ~1000 tokens (palabras), marcarlo como cacheable evita pagarlo en cada llamada.

```python
def build_messages(system_prompt: str, user_input: str) -> list[dict]:
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},  # OpenRouter lo pasa al proveedor
                },
                {
                    "type": "text",
                    "text": user_input,
                },
            ],
        }
    ]
```

---

## 7. Pipeline completo

```python
class BudgetExceededError(Exception):
    pass

def process(
    text: str,
    tracker: CostTracker,
    *,
    client: OpenAI | None = None,
    system_prompt: str = "",
) -> tuple[str, CostTracker]:
    if tracker.over_budget:
        raise BudgetExceededError(
            f"Presupuesto agotado: ${tracker.total_cost:.4f} / ${tracker.budget_usd:.2f}"
        )

    model = select_model(len(text), item_count=0)
    _client = client or get_client()

    response = call_with_retry(lambda: _client.chat.completions.create(
        model=model,
        messages=build_messages(system_prompt, text),
    ))

    record = CostRecord(
        model=model,
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
        cost_usd=extract_cost(response),   # costo real de OpenRouter
    )

    return response.choices[0].message.content, tracker.add(record)
```

---

## Buenas prácticas

- **Elige el modelo con el brief en mano**: compara calidad necesaria vs precio del día en openrouter.ai/models.
- **Establece el tope antes de procesar**: `CostTracker.from_env()` lo lee de `.env`.
- **Loguea cada selección de modelo**: ayuda a ajustar umbrales con datos reales.
- **Usa caché** para system prompts que se repiten en muchas llamadas.
- **Nunca reintentar errores de autenticación**: solo gastarías más presupuesto.

## Anti-patrones

- Hardcodear nombres de modelo en el código — van en `.env`.
- Calcular el costo a mano con precios fijos — usar `usage.cost` de la respuesta.
- Reintentar todos los errores — solo los transitorios.
- Ignorar `over_budget` antes de cada llamada.
- Mutar el CostTracker en vez de crear uno nuevo — dificulta auditar el gasto.
