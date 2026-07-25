# AGENT.md — Workers Project

## Project Overview

Background job processing for the 30ai platform. Workers listen on a Celery
queue, parse uploaded documents via Modal/Docling, generate embeddings via
OpenAI, and persist results to a PostgreSQL database (with pgvector).

---

## Architecture

```
src/
  main.py                 — Celery app & task definitions
  generate_embeddings.py  — Text chunking + OpenAI embedding pipeline
  parse_document.py       — Modal-hosted Docling parser (deployed separately)
  __init__.py             — Makes `src` a package (required for relative imports)
```

**Local dependency packages** (in `../../packages/`):

| Package    | Purpose                                  |
|------------|------------------------------------------|
| `database` | SQLModel models, DB session (`get_db`)   |
| `s3`       | Cloudflare R2 client (`R2Client`)        |

The `pyproject.toml` wires these via `[tool.uv.sources]`.

---

## How to Run & Test

```bash
# Run all tests
uv run pytest

# Run a specific test file
uv run pytest tests/test_generate_embeddings.py -v

# Run a specific test class
uv run pytest tests/test_main.py::TestFailJob -v
```

All tests are in `tests/`.  **32 tests**, all pass.

---

## Key Patterns & Gotchas

### 1. Module-level imports of `get_db`

`upload_embeddings` (in `generate_embeddings.py`) and `_fail_job` (in `main.py`)
both do:

```python
from database.session import get_db
```

This creates a **module-level reference** that survives even if you later patch
`database.session.get_db`.  When writing tests you **must patch the consumer's
reference**, not the origin:

```python
# ✅ Correct — patch where it's consumed
patch("src.generate_embeddings.get_db", mock_get_db)

# ❌ Wrong — does not affect already-imported references
patch("database.session.get_db", mock_get_db)
```

### 2. `contextmanager(get_db)()` requires a real generator

The production code uses:

```python
from contextlib import contextmanager

with contextmanager(get_db)() as db:
    ...
```

A plain `MagicMock` as `get_db` will cause `RuntimeError("generator didn't
stop")` because `next()` on a MagicMock never raises `StopIteration`.

**Fixture fix** — use `side_effect` with a real generator function:

```python
def _mock_get_db_factory(session):
    def _gen():
        yield session
    return MagicMock(side_effect=_gen)
```

(The helper lives in `tests/conftest.py`.)

### 3. Modal-decorated classes cannot be instantiated directly

`@app.cls(...)` transforms the class into a `modal.cls.Cls` instance.  Access
the underlying Python class and raw functions via Modal internals:

```python
user_cls = DoclingParser._get_user_cls()                    # original class
instance = user_cls()                                        # plain instance
raw_fn = DoclingParser._get_partial_functions()[name]._get_raw_f()  # undecorated function
raw_fn(instance, *args)                                      # call directly
```

This avoids KeyErrors from Modal's `_modal_functions` descriptor.

### 4. Celery `bind=True` tasks

Tasks decorated with `bind=True` wrap the original function.  The resulting
`task.run` has the **original signature minus `self`** (Celery binds it).

| Call method            | What happens                                     |
|------------------------|--------------------------------------------------|
| `task.delay(a, b)`     | Goes through Celery worker — not for unit tests |
| `task(a, b)`           | Goes through `Task.__call__` — prepends self     |
| `task.run(a, b)`       | Calls the original function **directly**         |

For tests, always use `task.run(...)` and call `task.push_request()` to
populate `self.request.id` when the task body reads it.

### 5. Local imports in function bodies

`process_document` in `parse_document.py` does `import httpx` **inside** the
method (not at module top-level).  Patching via `"src.parse_document.httpx"` does
not work because `httpx` is never assigned as a module attribute.

**Fix** — pre-populate `sys.modules` with a mock:

```python
with patch.dict("sys.modules", {"httpx": MagicMock()}):
    ...
```

### 6. pgvector requires 1536-dim embeddings

The `DocumentChunk.embedding` column is defined as `Vector(1536)`.  Tests that
write embeddings to a real or mocked DB session must use lists of length 1536.

---

## Running Validate Tasks

You can run `uv run pytest` from this directory to validate the code.

## Useful Commands

```bash
uv run pytest -v                          # verbose
uv run pytest -x                          # stop on first failure
uv run pytest --tb=long                   # full tracebacks
uv run pytest tests/ --coverage           # if pytest-cov is installed
```
