---
name: verification-loop
description: Six-phase verification for Python projects — lint, types, tests, security, diff review, and API contract tests against DISENO.md cases. Run after completing a feature, before creating a PR, and always before git push.
license: MIT
metadata:
  origin: ECC (adapted for Python + FastAPI + hackathon contract tests)
---

# Verification Loop

Run all phases in order. Stop and fix before continuing if a phase fails.

## Phase 1: Lint

```bash
ruff check . 2>&1 | head -30
```

Reports style and logic errors. Fix all errors; warnings are optional.

## Phase 2: Type check

```bash
pyright . 2>&1 | head -30
```

Reports type inconsistencies (variables usados con el tipo equivocado). Fix critical errors.

## Phase 3: Tests

```bash
pytest --tb=short -q 2>&1 | tail -40
```

Report:
- Total: X
- Passed: X
- Failed: X
- Coverage (if configured): X%

Target: 0 failures before push.

## Phase 4: Security — OBLIGATORIO antes de cada push

```bash
# Secretos sueltos en código fuente
grep -rn "OPENROUTER_API_KEY\s*=" --include="*.py" . | grep -v ".env" | grep -v "os.environ" | grep -v "os.getenv"
grep -rn "X-Eval-Token\s*=" --include="*.py" . | grep -v ".env" | grep -v "os.environ"
grep -rn "sk-or-" --include="*.py" . 2>/dev/null | head -10

# Verificar que .env NO está rastreado por git
git ls-files --error-unmatch .env 2>&1 | grep -q "did not match" && echo "✓ .env no está en git" || echo "⚠ ALERTA: .env está en git — quítalo antes de push"

# .env no debe aparecer en el diff del commit
git diff --cached --name-only | grep "^\.env$" && echo "⚠ ALERTA: .env está en el staging area" || echo "✓ .env no en staging"
```

Si algún secreto aparece en código fuente: STOP. No hacer push.

## Phase 5: Diff review

```bash
git diff --stat
git diff HEAD~1 --name-only 2>/dev/null || git diff --cached --name-only
```

Revisar cada archivo cambiado:
- ¿Hay cambios no intencionados?
- ¿Falta manejo de errores donde el brief lo exige?
- ¿Aparece algún secreto o valor hardcodeado?

## Phase 6: Contract tests — casos del diseño

Con el servidor corriendo localmente (`uvicorn app.main:app --port 8000`), ejecutar los casos de DISENO.md y verificar que cada respuesta coincide con el resultado esperado medido.

Casos mínimos antes de entregar (T01–T14):

```bash
BASE="http://localhost:8000"
TOKEN="<token-de-prueba>"

# T01 — libro exacto
curl -s -X POST $BASE/run -H "X-Eval-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"case_id":"T01","type":"precio_libro","params":{"title":"It'\''s Only the Himalayas"}}' | python -m json.tool

# T03 — segundo libro distinto (evita valor hardcodeado)
curl -s -X POST $BASE/run -H "X-Eval-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"case_id":"T03","type":"precio_libro","params":{"title":"Sharp Objects"}}' | python -m json.tool
# Esperado: {"price_gbp": 47.82, "stock": 20}

# T06 — borde exacto ≤ (Vagabonding a £36.94 debe incluirse)
curl -s -X POST $BASE/run -H "X-Eval-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"case_id":"T06","type":"contar_categoria","params":{"category":"Travel","max_price_gbp":36.94}}' | python -m json.tool
# Esperado: {"count": 4}

# T08 — count 0 (categoría existe, ningún libro cumple)
curl -s -X POST $BASE/run -H "X-Eval-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"case_id":"T08","type":"contar_categoria","params":{"category":"Travel","max_price_gbp":20.00}}' | python -m json.tool
# Esperado: status "ok", count 0

# T12 — token incorrecto
curl -s -X POST $BASE/run -H "X-Eval-Token: token-malo" \
  -H "Content-Type: application/json" \
  -d '{"case_id":"T12","type":"precio_libro","params":{"title":"Sharp Objects"}}' | python -m json.tool
# Esperado: HTTP 401, {"error": "unauthorized"}

# T13 — params faltante
curl -s -X POST $BASE/run -H "X-Eval-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"case_id":"T13","type":"precio_libro"}' | python -m json.tool
# Esperado: HTTP 400, {"error": "bad_request"}

# T14 — tipo desconocido
curl -s -X POST $BASE/run -H "X-Eval-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"case_id":"T14","type":"tipo_inventado","params":{}}' | python -m json.tool
# Esperado: HTTP 200, {"status": "error"}

# GET /health
curl -s $BASE/health
# Esperado: {"status": "ok"}
```

Ver DISENO.md para los 14 casos completos con todos los valores esperados.

## Reporte final

```
VERIFICATION REPORT
===================
Lint:      [PASS/FAIL] (X errores)
Types:     [PASS/FAIL] (X errores)
Tests:     [PASS/FAIL] (X/Y pasaron)
Security:  [PASS/FAIL] (.env fuera de git: sí/no, secretos en código: X)
Diff:      [X archivos cambiados]
Contracts: [X/14 casos correctos]

Overall: [LISTO / NO LISTO] para push
```
