# Nomi AI Service — Senior Engineering Analysis

> Analysed: 2026-05-17  
> Codebase: FastAPI 0.136 · Python 3.11 · Pydantic v2 · Ollama + Groq fallback · Redis cache  
> Total source files: 12 Python modules · 8 test files · ~86 tests

---

## Table of Contents

1. [Architecture](#1-architecture)
2. [SOLID Principles](#2-solid-principles)
3. [Design Patterns](#3-design-patterns)
4. [FastAPI Best Practices](#4-fastapi-best-practices)
5. [Pydantic](#5-pydantic)
6. [Security](#6-security)
7. [Performance](#7-performance)
8. [Error Handling](#8-error-handling)
9. [Testing](#9-testing)
10. [Clean Code](#10-clean-code)
11. [CI/CD Readiness](#11-cicd-readiness)
12. [Dependency Management](#12-dependency-management)
13. [Prioritised Action Plan](#13-prioritised-action-plan)

---

## 1. Architecture

### Verdict: Good separation, one async-boundary violation, one missing abstraction

The layering is deliberate and mostly clean:

```
main.py          — app wiring, middleware, lifespan, health
config.py        — env-vars, startup validation
routers/         — HTTP boundary (request/response mapping)
services/        — domain logic (orchestrator, providers, cache, sanitizer, validators)
models/          — Pydantic schema definitions
```

### Findings

**🟡 `check_ollama_health()` is called in two places with different async contracts**  
`main.py:67` calls it as a plain sync function inside an `async` lifespan. `routers/recommendations.py:112` wraps it correctly with `run_in_threadpool`. No single wrapper owns this responsibility; callers must remember to wrap it.

**🟡 `get_cache_service()` bypasses FastAPI dependency injection**  
`routers/recommendations.py:63` and `main.py:77,153` each call the module-level singleton factory directly. This couples the router to a concrete import, complicates unit-testing the route in isolation, and makes it impossible to swap cache implementations at runtime.

```python
# Current (direct import + global singleton)
cache = get_cache_service()

# Better
async def get_cache(cache: CacheService = Depends(get_cache_service)) -> CacheService:
    return cache
```

**🟢 No god functions or mixed responsibilities found.** Each module has a single, clear job. The orchestrator does not know about HTTP; the router does not know about prompts.

---

## 2. SOLID Principles

### Single Responsibility Principle

| Module | Responsibility | Verdict |
|---|---|---|
| `config.py` | Env-var reading + startup validation | ✅ SRP OK |
| `services/orchestrator.py` | Fallback iteration only | ✅ SRP OK |
| `services/ollama_service.py` | Prompt building + HTTP call + JSON parsing | ⚠️ Three concerns |
| `services/validators.py` | Post-LLM normalisation | ✅ SRP OK |
| `services/sanitizer.py` | Input scrubbing | ✅ SRP OK |
| `services/cache_service.py` | Redis access | ✅ SRP OK |

**🟡 `ollama_service.py` has three concerns:** prompt building (`_build_batch_prompt`), HTTP transport (`get_recommendations`), and JSON repair (`extract_json`). This is the most complex file and the hardest to unit-test in isolation. Extracting `extract_json` into `services/json_utils.py` and `_build_batch_prompt` into a `PromptBuilder` class would make each independently testable.

### Open/Closed Principle

**✅ Excellent.** `LLMOrchestrator` iterates over `Sequence[LLMProvider]`. Adding a third provider (e.g., Anthropic) requires zero changes to the orchestrator or router.

### Liskov Substitution Principle

**✅ N/A by design.** The `LLMProvider` Protocol uses structural subtyping (`@runtime_checkable`). There is no inheritance chain to violate. This is the right approach in Python.

### Interface Segregation Principle

**✅ Good.** `LLMProvider` exposes exactly two methods (`is_available`, `get_recommendations`). No fat interface.

### Dependency Inversion Principle

**🟡 Partial.** `LLMOrchestrator` depends on the `LLMProvider` abstraction — correct. But `main.py:63` instantiates concrete providers directly:

```python
providers = [OllamaProvider(), GroqProvider()]   # main.py:63
```

This is the composition root, so it is acceptable. The real gap is `CacheService` and `check_ollama_health` being called as module-level functions rather than injected via `Depends`, which prevents runtime swapping and forces monkey-patching in tests.

---

## 3. Design Patterns

### Patterns Present

| Pattern | Location | Quality |
|---|---|---|
| Strategy | `LLMProvider` Protocol + two concrete providers | ✅ Clean |
| Chain of Responsibility / Fallback | `LLMOrchestrator.execute` | ✅ Clean |
| Singleton (module-level) | `_client` in ollama/groq, `_cache_service` | ⚠️ Thread-unsafe across forks |
| Template Method (implicit) | `normalize_recommendation_items` shared across providers | ✅ Good |

### Missing Patterns That Would Materially Help

**🔴 Circuit Breaker — absent, causes real latency cost**

When Ollama is down, every request waits `OLLAMA_TIMEOUT_SECONDS` (default 30 s) before falling back to Groq. Under production load this means:

- P50 latency with Ollama down: 30 s + Groq latency
- Threadpool exhaustion after a few concurrent requests

A simple circuit breaker on `OllamaProvider` would detect consecutive failures and skip Ollama for a cool-down window:

```python
class CircuitBreaker:
    def __init__(self, threshold: int = 3, reset_after: float = 60.0): ...
    def call(self, fn, *args, **kwargs): ...
```

**🟡 Factory for providers — not strictly needed but would clean up `main.py`**

`main.py:63` would become:

```python
providers = LLMProviderFactory.build_from_config()
```

This keeps `main.py` free from knowing about all possible providers as the list grows.

**🟡 Repository Pattern — not needed for this microservice**  
Products arrive in the request body (passed through from the Spring backend). No persistence layer exists, so this is intentionally absent and correct.

---

## 4. FastAPI Best Practices

### Dependency Injection

**🟡 `_get_orchestrator` is manual DI, not `Depends`**

`routers/recommendations.py:39–43`:
```python
def _get_orchestrator(request: Request) -> LLMOrchestrator:
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=503, ...)
    return orchestrator
```

FastAPI's `Depends` system provides caching, testability, and OpenAPI documentation for free. The canonical approach:

```python
def get_orchestrator(request: Request) -> LLMOrchestrator:
    ...

@router.post("/recommendations")
async def recommend(
    body: RecommendationRequest,
    orchestrator: LLMOrchestrator = Depends(get_orchestrator),
    cache: CacheService = Depends(get_cache_service),
):
```

**🟡 `get_cache_service()` is called three times as a plain function** (`main.py:77`, `main.py:153`, `routers/recommendations.py:63`). The singleton hides this but it should be injected.

### Lifespan Events

**🔴 Blocking network call inside `async` lifespan — blocks the event loop**

`main.py:67`:
```python
async def lifespan(app: FastAPI):
    ...
    check_ollama_health()          # ← BLOCKING sync I/O, no run_in_threadpool
```

`check_ollama_health()` calls `OllamaClient.list()` which makes a synchronous HTTP request. Inside an `async` function this blocks the entire event loop until the call completes (or the default 30 s timeout fires). Correct fix:

```python
from fastapi.concurrency import run_in_threadpool

try:
    await run_in_threadpool(check_ollama_health)
except Exception as exc:
    logger.warning(...)
```

### Router Organisation

**✅ Clean.** Single router file is appropriate for this microservice size. Prefix and tags applied correctly.

### Response Models

**✅ Used correctly** on all endpoints. `response_model=RecommendationResponse` on POST, `response_model=OllamaHealthResponse` on GET.

### Background Tasks

**✅ Not needed here.** `run_in_threadpool` for sync LLM calls is the correct pattern.

### Rate Limiting Order — Auth Bypasses Rate Limiter for Unauthenticated Requests

**🔴 Critical security gap** (see Security section §6).

---

## 5. Pydantic

### Model Design

**🟡 `RecommendationResponse.generated_by` hardcodes `"phi3"` as default**

`models/schemas.py:133`:
```python
class RecommendationResponse(BaseModel):
    generated_by: str = "phi3"
```

This default is wrong: when Groq handles the request, `generated_by` is set to `f"groq/{GROQ_MODEL}"`. If a new provider forgets to set `generated_by`, the response silently lies about the source. The field should have no default, or default to `""`:

```python
generated_by: str = Field(default="", description="LLM provider that generated this response")
```

Additionally, the default is coupled to a specific model name, not the configured `OLLAMA_MODEL`. If someone changes `OLLAMA_MODEL=mistral`, the default still says `"phi3"`.

**🟡 `ProductRecommendation.product_id` has no `ge=1` constraint**

`models/schemas.py:122–127`: `product_id: int` is unconstrained, while `AvailableProduct.id: int = Field(ge=1)`. Since `normalize_recommendation_items` cross-references against the catalogue, a negative ID can never survive, but the schema itself is inconsistent.

**🟡 No cross-field validator: `max_recommendations` vs `len(available_products)`**

A request with `max_recommendations=20` and `available_products=[one_item]` is valid per schema. The LLM is asked for 20 recommendations from 1 product. A `@model_validator(mode="after")` can cap this:

```python
@model_validator(mode="after")
def _cap_max_recommendations(self) -> "RecommendationRequest":
    cap = len(self.available_products)
    if self.max_recommendations > cap:
        self.max_recommendations = cap
    return self
```

**🟡 `_INJECTION_PATTERNS` regex uses `\b` (ASCII word boundary)**

`models/schemas.py:40–44`: In Python's `re` module, `\b` only recognises ASCII word characters by default. The pattern `r"\b(ignore)\b"` would fail to detect `"ígnore"` (accented variant) or `"IGNORE"` adjacent to an accented character. Use `re.UNICODE` flag or replace `\b` with `(?<!\w)(?!\w)` with `re.UNICODE`.

**✅ Pydantic v2 API used correctly throughout.** `field_validator` (not `validator`), `model_dump()` (not `.dict()`), `Field(ge=...)` syntax — all v2-idiomatic.

**✅ Enum-typed `DietaryRestriction`** prevents free-text injection via the restrictions field entirely. This is the strongest possible defence for that field.

**✅ `_validate_user_text` shared validator** reduces duplication across `nombre`, `categoria`, and `preferences`. Good design.

---

## 6. Security

### API Key Enforcement

**✅ `hmac.compare_digest` used correctly** (`main.py:115`). Constant-time comparison prevents timing attacks.

**✅ Startup abort in production** if `API_SECRET_KEY` is absent or matches a blocklist of insecure defaults (`config.py:55–86`). Good defence.

### Rate Limiting

**🔴 Unauthenticated requests are not rate-limited**

Middleware execution order in this app (LIFO):
1. `CORSMiddleware` (outermost)
2. `validate_api_key` (returns 401 and short-circuits)
3. `SlowAPIMiddleware` (never reached for unauthenticated requests)

The `@limiter.limit` decorator on the route is also unreachable for 401 responses. An attacker can brute-force API keys at full speed — there is no throttle on authentication failures.

Fix: add a rate limit at the middleware level, or apply a slowapi limit to the auth middleware itself, or use a blanket IP-based limit before auth runs.

**🟡 Rate limit key uses `api_key[:16]` — timing side-channel**

`services/rate_limit.py:19–21`:
```python
api_key_part = api_key[:16] if api_key else "anon"
```

Two different valid API keys that share a 16-character prefix would share a rate-limit bucket. More critically, an attacker can probe whether two requests share a prefix by observing rate limit headers — this leaks partial key information. Hash the key instead:

```python
import hashlib
api_key_part = hashlib.sha256(api_key.encode()).hexdigest()[:16] if api_key else "anon"
```

### Prompt Injection Defences

**✅ Multi-layer defence:**
1. Pydantic schema rejects dangerous characters and injection keywords
2. `scrub_for_prompt` / `scrub_list_for_prompt` applied to all user-controlled fields before prompt assembly
3. System prompt explicitly labels `<USER_DATA>` and `<PRODUCTS>` as data, not instructions
4. `normalize_recommendation_items` discards any product ID that wasn't in the original catalogue (anti-hallucination)
5. `safe_reason` HTML-escapes LLM output before returning it to the client

This is a strong, defence-in-depth posture. Well done.

### PII in Logs

**✅ `hash_user_id` used in all log lines** — actual user IDs never appear in logs.

**✅ `SecretFilter` installed on root logger** — redacts Bearer tokens, API keys, and authorization headers.

**🟡 Groq error logging loses error detail** (`groq_service.py:108`):
```python
logger.error("Groq falló: %s", type(exc).__name__)
```
Only the exception type is logged, not the message. If Groq returns a specific error code (quota exceeded, invalid model, etc.) that information is silently discarded. The error chain (`from exc`) preserves it for raise propagation but not for observability. Log `exc` (not just its type) at WARNING level to preserve detail without leaking it externally.

### `/docs` in Production

**✅ Disabled correctly** via `docs_url=None if IS_PRODUCTION else "/docs"` and `openapi_url=None`.

### Information Disclosure via `/health/ready`

**🟡 `/health/ready` is public and reveals infrastructure topology**

`main.py:143–164` returns:
```json
{"ready": true, "ollama": "up", "groq_configured": true, "cache": "up"}
```

This is unauthenticated. An attacker learns whether Groq fallback is configured and whether Redis is live. Consider returning only `{"ready": true}` publicly, with full detail behind API key auth.

### `.env` Copied into Docker Image

**🔴 No `.dockerignore` file exists.** `Dockerfile:20` copies the entire build context:
```dockerfile
COPY --chown=nomi:nomi . .
```
If a `.env` file with real credentials exists at build time, it is baked into the image layer. Anyone with pull access to the registry can extract it with `docker run --rm <image> cat /app/.env`.

Fix: create `.dockerignore` with at minimum:
```
.env
.git
__pycache__
*.pyc
tests/
.pytest_cache/
```

---

## 7. Performance

### Redis Pool

**✅ `ConnectionPool.from_url()` with `socket_connect_timeout=2` and `socket_timeout=2`** — correct. Pool is reused across requests. `health_check_interval=30` allows the pool to detect dead connections.

**🟡 `is_available` property is a lie after Redis goes down post-startup**

`cache_service.py:62`: `return self._pool is not None`. If Redis dies after startup, `_pool` is still not None, but operations fail (caught by `get`/`set` with silent degradation — which is correct). However, the `is_available` flag returned in `/health/ready` would still show `"up"` when Redis is effectively unreachable. The flag is misleading.

**🟡 Docstring claims lazy reconnection but code never reconnects**

`cache_service.py:7`: *"Reconexión perezosa: si Redis cae al arranque, futuros requests intentan reconectar"*. In practice, if `_pool` is set to `None` in `__init__`, it stays `None` forever because `get_cache_service()` returns the same singleton. `get`/`set` no-op on `not is_available`. There is no reconnection path.

Fix: Remove the misleading docstring, or implement periodic reconnection by attempting `CacheService()` again on cache miss when `_pool is None`.

### Async/Await Consistency

**🔴 Blocking call in async lifespan** — already noted in §4.

**✅ `run_in_threadpool` used correctly** in the router for all sync I/O (Ollama, Groq, Redis).

**✅ `readiness()` and `health()` are sync endpoints** — FastAPI automatically runs them in the default threadpool executor. The blocking `check_ollama_health()` call inside `readiness()` is safe in this context but can starve the threadpool under probe pressure from Kubernetes.

### Ollama Timeout Under Load

**🟡 Default `OLLAMA_TIMEOUT_SECONDS=30` with no circuit breaker**

With 4 Gunicorn workers and concurrent requests, if Ollama is down:
- Each request holds a threadpool thread for 30 s before falling back
- 4 workers × threadpool exhaustion = service effectively unavailable
- Without a circuit breaker, Groq fallback latency = 30 s + Groq latency

Consider reducing `OLLAMA_TIMEOUT_SECONDS` to 10–15 s and implementing a circuit breaker.

### Gunicorn Worker Configuration

**🟡 `--workers 4` is hardcoded in Dockerfile**

The recommended formula is `(2 × CPU_CORES) + 1`. In a Kubernetes pod with variable CPU limits, 4 workers may be too many (causing memory pressure) or too few (wasting cores).

```dockerfile
# Better: respect WEB_CONCURRENCY env var (standard convention)
CMD ["sh", "-c", "gunicorn main:app -k uvicorn.workers.UvicornWorker \
    --workers ${WEB_CONCURRENCY:-4} ..."]
```

---

## 8. Error Handling

### HTTP Exception Coverage

**✅ Route-level exception handling is thorough:**
- `AllProvidersFailedError` → 503 with `error_id`
- `HTTPException` re-raised
- Bare `Exception` → 500 with `error_id`
- `ValidationError` from corrupted cache → logged + regenerated

**✅ `error_id` pattern** prevents leaking internal details while enabling log correlation.

### LLM Fallback Failure

**🟡 `AllProvidersFailedError` inherits from `RuntimeError`**

`orchestrator.py:20`: This makes it hard to distinguish from other `RuntimeError` exceptions if an intermediate layer wraps them. A custom base class hierarchy is cleaner:

```python
class AIServiceError(Exception): ...
class AllProvidersFailedError(AIServiceError): ...
```

### Unhandled Edge Cases

**🟡 `response["message"]["content"]` access in `ollama_service.py:193`**

```python
content = response["message"]["content"].strip()
```

If the Ollama SDK returns a response where `message` is missing or `content` is `None`, this raises `KeyError` or `AttributeError`. These are not caught by the provider-level `except` block (which only catches `httpx.TimeoutException, ollama.RequestError, ollama.ResponseError`). They propagate to the orchestrator's broad `except Exception`, which handles them, but the log message will be misleading ("Error inesperado" instead of "Respuesta inválida").

Fix:
```python
content = (response.get("message", {}).get("content") or "").strip()
if not content:
    raise RuntimeError("Respuesta vacía del modelo")
```

**🟡 `extract_json` repair strategies can produce semantically wrong data**

`ollama_service.py:144–148`: Appending `"}"`, `"]}"`, etc. to truncated JSON will produce valid JSON from invalid LLM output. This could reconstruct a structurally valid but semantically empty recommendations list, causing the orchestrator to return zero recommendations instead of failing over to Groq. The post-LLM validation in `normalize_recommendation_items` mitigates this, but a zero-recommendation result is silently accepted as success.

---

## 9. Testing

### Test Classification

| File | Type | What it tests |
|---|---|---|
| `test_api_security.py` | Integration | Middleware, auth, input validation end-to-end |
| `test_fallback.py` | Unit | Orchestrator fallback logic with mocked providers |
| `test_cache_service.py` | Unit | CacheService with mocked Redis client |
| `test_prompt_injection.py` | Unit | Pydantic schema rejection of malicious inputs |
| `test_validate_recommendations.py` | Unit | Post-LLM normalisation logic |
| `test_sanitizer.py` | Unit | Scrubbing/escaping functions |
| `test_prompt_builder.py` | Unit | Prompt construction + `extract_json` |
| `test_logging_filter.py` | Unit | Secret redaction in logs |

### Coverage Gaps

**🔴 Zero tests for `GroqProvider.get_recommendations()`**

`services/groq_service.py` has no dedicated test file. The entire HTTP call, JSON parsing, and error path for the cloud fallback is untested. This is particularly risky because Groq is the safety net when Ollama fails.

Minimum test scenarios needed:
- Successful response (array of items)
- Response with no JSON array → `RuntimeError`
- Malformed JSON → `RuntimeError`
- HTTP exception → `RuntimeError`

**🟡 `OllamaProvider.get_recommendations()` has no integration test**

`test_prompt_builder.py` tests `_build_batch_prompt` and `extract_json` in isolation. But the full `OllamaProvider.get_recommendations()` flow (with mocked `OllamaClient`) is not tested. Mocking `_get_client()` and asserting on `client.chat()` calls + response handling would cover this.

**🟡 Cache corruption recovery path is untested**

`routers/recommendations.py:75–78` handles a corrupted cache entry (catches `ValidationError`, logs, regenerates). No test verifies this path.

**🟡 Readiness endpoint failure modes are untested**

No test for `GET /health/ready` when both Ollama and Groq are unavailable (should return 503).

**🟡 `pytest-asyncio` is installed but no async tests exist**

All tests are synchronous. If this is intentional (all async paths are wrapped in `run_in_threadpool`), remove the dependency. If future async tests are planned, add `asyncio_mode = "auto"` to `pytest.ini`.

### Test Isolation

**🟡 `test_api_security.py` modifies `os.environ` at module level**

```python
os.environ["ENV"] = "development"
os.environ["API_SECRET_KEY"] = "..."
```

These run before `conftest.py`'s `setdefault` calls have any effect (because the module is imported after conftest runs). This creates an implicit ordering dependency between test files. A pytest fixture with `monkeypatch.setenv` would be isolated and deterministic.

**🟡 `reset_client_for_tests()` functions leak into production code**

`ollama_service.py:47–49`, `groq_service.py:42–44`: Test helpers mixed into production modules. These should either be in the test files themselves (via `unittest.mock.patch`) or in a `conftest.py` fixture that patches the module-level `_client`.

### Positive Notes

**✅ `test_fallback.py` is exemplary** — uses `MagicMock` correctly, tests all orchestrator state transitions, parametrised edge cases.

**✅ `test_prompt_injection.py` parametrised coverage** of injection payloads is thorough and valuable.

---

## 10. Clean Code

### Naming

**✅ Consistent and clear.** Domain terms in Spanish (matching the business domain) are used uniformly. Technical identifiers in English. No abbreviation abuse.

### Function Length

**✅ All functions are short.** Longest is `_build_batch_prompt` at ~30 lines with one clear purpose.

### Magic Strings / Numbers

**🟡 `"2.0.0"` hardcoded in two places**

`main.py:84` (FastAPI app definition) and `main.py:140` (health endpoint response). No single source of truth for the service version:

```python
# config.py
VERSION: Final[str] = _get_str("SERVICE_VERSION", "2.0.0")
```

**🟡 `"phi3"` as default in `RecommendationResponse.generated_by`**

Already noted in §5. Magic string coupled to infrastructure config.

**🟡 `[:16]` in rate limit key**

`rate_limit.py:20`: The number 16 is not explained. A comment or named constant (`_KEY_PREFIX_LEN = 16`) would make the intent explicit.

### Dead Code

**🟢 `generate_secret_key()` in `config.py:99–101`** is never called from within the codebase. It's documented as a deploy helper but there's no CLI entrypoint or script that uses it. Either wire it to a CLI command (`python -m config generate-key`) or remove it.

### Comments

**✅ Comments explain WHY, not WHAT.** Module docstrings are purposeful and describe design decisions. No commented-out code blocks. No redundant inline comments.

### Test Helpers in Production Code

**🟡 `reset_client_for_tests()` functions** (see §9) are test-only helpers that pollute production modules.

---

## 11. CI/CD Readiness

### Dockerfile Quality

**🔴 No `.dockerignore` — secrets can be baked into the image**  
Already detailed in §6.

**🔴 No multi-stage build — test dependencies shipped to production**

```dockerfile
FROM python:3.11-slim AS base
...
RUN pip install --no-cache-dir -r requirements.txt   # installs pytest, pytest-asyncio
```

`pytest` and `pytest-asyncio` are installed in the production image because they live in `requirements.txt`. A multi-stage Dockerfile separates build/test from runtime:

```dockerfile
FROM python:3.11-slim AS base
...
FROM base AS dev
RUN pip install -r requirements-dev.txt

FROM base AS production
RUN pip install -r requirements.txt   # production-only deps
```

**🟡 `HEALTHCHECK` uses `/health/ready` instead of `/health`**

`Dockerfile:26–27`:
```dockerfile
HEALTHCHECK CMD curl -fsS http://localhost:8001/health/ready || exit 1
```

`/health/ready` checks Ollama and Redis. If Ollama is temporarily down but Groq is configured (service is functional), the container would report unhealthy to the orchestrator and get killed/restarted unnecessarily. Use `/health` (liveness) for the Docker `HEALTHCHECK` and let the orchestrator/Kubernetes decide readiness separately.

**🟡 Gunicorn workers hardcoded** — already noted in §7.

**🟡 `apt-get upgrade -y` in Dockerfile**

`Dockerfile:10`: `apt-get upgrade -y` upgrades all packages including the base OS, making builds non-reproducible (each build may install different versions). Pin base image updates via Docker image digest (`python:3.11-slim@sha256:...`) instead.

### Startup Validation

**✅ Config validates critical vars at import time** (`config.py:95–96`). The process aborts before accepting traffic if production keys are missing. This is correct.

### Observability Gaps

**🟡 No structured JSON logging**

Log output is human-readable format (`%(asctime)s [%(levelname)s]...`). In a containerised environment, structured JSON logs integrate with log aggregators (Loki, Datadog, CloudWatch) without parsing:

```python
# Use python-json-logger or structlog
logging.basicConfig(handlers=[JSONHandler()])
```

**🟡 No metrics endpoint (Prometheus)**

No `/metrics` endpoint. Gunicorn worker count, request latency, LLM provider success/failure rates, cache hit ratio — none are exported. In production this is a blind spot.

**🟡 No distributed tracing**

No OpenTelemetry instrumentation. LLM call latency is not attributable to individual requests without trace IDs.

**🟢 `error_id` in 500/503 responses** partially compensates by enabling log correlation on errors.

### CI/CD Configuration

**🟡 No CI pipeline file** (`.github/workflows/`, `gitlab-ci.yml`, etc.) is present in the repository. Tests cannot be automatically verified on PRs.

### Version Not Centralised

**🟡 `"2.0.0"` in `main.py`** (×2). Should live in `config.py` or `pyproject.toml`.

---

## 12. Dependency Management

### requirements.txt

```
fastapi==0.136.1
uvicorn==0.46.0
gunicorn==23.0.0
ollama==0.6.1
pydantic==2.13.3
groq==0.28.0
redis==5.0.1
python-dotenv==1.0.1
slowapi==0.1.9
httpx==0.28.1
pytest==8.3.4           ← test-only
pytest-asyncio==0.25.0  ← test-only
```

**🔴 Test dependencies mixed with production runtime dependencies**

`pytest` and `pytest-asyncio` have no business being in the production Docker image. Split into:
- `requirements.txt` — production runtime
- `requirements-dev.txt` — test + lint + type-check tools (`-r requirements.txt` at top)

**🟡 No `pyproject.toml`**

The modern Python packaging standard. `pyproject.toml` consolidates `pytest` configuration, tool settings (ruff, mypy), and dependency groups (dev, test, prod). `pytest.ini` is redundant once `pyproject.toml` exists.

**🟡 `pytest.ini` has no coverage configuration**

No `--cov`, `--cov-fail-under`, or `addopts`. Running tests gives no coverage report and no minimum coverage gate:

```ini
[pytest]
testpaths = tests
addopts = --cov=. --cov-report=term-missing --cov-fail-under=80
```

**🟢 All versions are pinned** — reproducible builds. Good.

**🟢 `httpx` is a direct dependency** (used in `groq_service.py` for `httpx.Timeout`), not just a transitive dep. Correct to list it explicitly.

**🟡 No type checking tooling configured** (mypy, pyright). The codebase uses type annotations throughout, but they are never statically verified. A `mypy` run would likely surface several issues in the module-level singleton patterns and the `Optional` usages.

---

## 13. Prioritised Action Plan

Sorted by impact (highest first). Estimated effort in parentheses.

### 🔴 Critical — Fix Before Production Traffic

| # | Issue | File | Fix |
|---|---|---|---|
| 1 | **No `.dockerignore`** — `.env` secrets baked into image | `Dockerfile` | Add `.dockerignore` excluding `.env`, `.git`, `tests/`, `__pycache__` |
| 2 | **Brute-force auth is unthrottled** — 401s not rate-limited | `main.py` | Add IP-based rate limit before auth middleware; or use `slowapi` on 401 path |
| 3 | **Blocking I/O in async lifespan** — blocks event loop at startup | `main.py:67` | Wrap `check_ollama_health()` with `await run_in_threadpool(check_ollama_health)` |
| 4 | **No Groq provider tests** — cloud fallback has zero coverage | — | Create `tests/test_groq_service.py` with mocked `Groq` client |
| 5 | **Multi-stage Dockerfile missing** — pytest in production image | `Dockerfile` | Add builder stage; split `requirements-dev.txt` |

### 🟡 Medium — Fix in Next Sprint

| # | Issue | File | Fix |
|---|---|---|---|
| 6 | **No circuit breaker** — 30 s timeout per request when Ollama down | `services/orchestrator.py` | Implement `CircuitBreaker` wrapper on providers |
| 7 | **Rate limit key leaks API key prefix** | `services/rate_limit.py:20` | Hash the API key before using as rate-limit bucket key |
| 8 | **`generated_by` default hardcodes `"phi3"`** | `models/schemas.py:133` | Remove default or use `OLLAMA_MODEL` from config |
| 9 | **`CacheService` docstring claims lazy reconnect, code doesn't** | `cache_service.py` | Fix docstring or implement periodic reconnection attempt |
| 10 | **Groq error logging loses error detail** | `services/groq_service.py:108` | Log full exception message at WARNING |
| 11 | **`is_available` misleading after Redis dies post-startup** | `cache_service.py:62` | Implement a live ping check or remove from health response |
| 12 | **`/health/ready` leaks infrastructure topology publicly** | `main.py:143` | Return only `{"ready": bool}` publicly; detail behind API key |
| 13 | **HEALTHCHECK uses readiness, not liveness** | `Dockerfile:26–27` | Change to `/health` |
| 14 | **Gunicorn workers hardcoded** | `Dockerfile:30` | Use `${WEB_CONCURRENCY:-4}` env var |
| 15 | **`AllProvidersFailedError` inherits `RuntimeError`** | `services/orchestrator.py:20` | Create `AIServiceError` base, have this inherit from it |
| 16 | **`response["message"]["content"]` unguarded** | `services/ollama_service.py:193` | Use `.get()` with None check |
| 17 | **`os.environ` set at module level in test file** | `tests/test_api_security.py:12–13` | Use `monkeypatch.setenv` fixtures |
| 18 | **`reset_client_for_tests()` in production modules** | `ollama_service.py:47`, `groq_service.py:42` | Use `unittest.mock.patch` in tests; remove from production modules |
| 19 | **Version string not centralised** | `main.py:84,140` | Define `VERSION` constant in `config.py` |
| 20 | **`_get_orchestrator` and cache not using `Depends`** | `routers/recommendations.py` | Refactor to proper FastAPI dependency injection |
| 21 | **No structured JSON logging** | `main.py:39` | Switch to `python-json-logger` or `structlog` |
| 22 | **No CI pipeline** | — | Add `.github/workflows/ci.yml` (lint + test + build) |

### 🟢 Minor — Address When Convenient

| # | Issue | File | Fix |
|---|---|---|---|
| 23 | **`pytest-asyncio` installed but no async tests** | `requirements.txt` | Remove or add `asyncio_mode = "auto"` to `pytest.ini` + write async tests |
| 24 | **No coverage gate in `pytest.ini`** | `pytest.ini` | Add `addopts = --cov=. --cov-fail-under=80` |
| 25 | **No `pyproject.toml`** | — | Migrate from `pytest.ini` + `requirements.txt` to `pyproject.toml` |
| 26 | **`generate_secret_key()` unused** | `config.py:99` | Wire to `python -m config generate-key` or delete |
| 27 | **`_b` word boundary in injection regex is ASCII-only** | `models/schemas.py:40` | Add `re.UNICODE` flag |
| 28 | **`ProductRecommendation.product_id` unconstrained** | `models/schemas.py:122` | Add `Field(ge=1)` |
| 29 | **`max_recommendations > len(products)` not validated** | `models/schemas.py` | Add `@model_validator` to cap |
| 30 | **No type checking configuration** | — | Add `mypy` or `pyright` to dev tooling |
| 31 | **No Prometheus `/metrics` endpoint** | — | Add `prometheus-fastapi-instrumentator` |
| 32 | **`apt-get upgrade -y` makes builds non-reproducible** | `Dockerfile:10` | Pin base image by digest |

---

## Summary Scorecard

| Area | Score | Key Issues |
|---|---|---|
| Architecture | 7/10 | Blocking lifespan call, missing DI via `Depends` |
| SOLID | 8/10 | Good overall; `ollama_service.py` has 3 concerns |
| Design Patterns | 6/10 | Missing circuit breaker is a production risk |
| FastAPI Practices | 6/10 | Manual DI, blocking lifespan call |
| Pydantic | 8/10 | Hardcoded default, missing cross-field validator |
| Security | 7/10 | Auth brute-force unthrottled, `.env` in image risk |
| Performance | 6/10 | No circuit breaker, blocking startup call |
| Error Handling | 8/10 | Good structure; minor unguarded accesses |
| Testing | 6/10 | Groq provider completely uncovered |
| Clean Code | 9/10 | Very readable; minor magic strings |
| CI/CD | 5/10 | No CI pipeline, no multi-stage build, no `.dockerignore` |
| Dependencies | 6/10 | Test deps in production image |

**Overall: 7/10.** The security fundamentals (HMAC auth, prompt injection defence, PII masking) and the orchestrator design are genuinely strong. The critical gaps are operational: the missing `.dockerignore`/multi-stage build (secret exposure risk), the unthrottled auth brute-force, the blocking startup call, and the complete absence of Groq provider tests.
