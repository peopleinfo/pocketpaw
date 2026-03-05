---
name: gradio-to-fastapi
description: Convert a Gradio Python app into a FastAPI REST API project. Use this skill whenever the user wants to extract API endpoints from a Gradio app, create a headless/server-only version of a Gradio app, build a REST API that mirrors Gradio functionality, wrap Gradio functions in FastAPI routes, or migrate from Gradio GUI to a pure API backend. Also triggers when the user mentions "gradio to api", "gradio to fastapi", "remove gradio gui", "headless gradio", "api from gradio", or wants to call Gradio logic from a server without the UI.
user-invocable: true
argument-hint: "<path_to_gradio_app.py> [approach: extract|proxy|mount]"
allowed-tools:
  - read_file
  - write_file
  - shell
  - list_dir
---

# Gradio to FastAPI Conversion Skill

This skill helps you convert a Gradio-based Python application into a clean FastAPI REST API — extracting the core logic and exposing it via standard HTTP endpoints.

## Strategy Selection

There are **3 approaches** depending on the user's situation. Ask which one fits if unclear:

### Approach A: Extract Core Logic (Recommended for production)

- Pull the business logic OUT of the Gradio app into a shared module
- Build a new FastAPI app that imports and calls that logic directly
- No dependency on Gradio at runtime
- Best for: new production APIs, microservices, clean architecture

### Approach B: Use `gradio_client` as a Proxy

- Keep the Gradio app running as-is
- Build a FastAPI app that calls the Gradio app via `gradio_client`
- The FastAPI app acts as a thin REST wrapper around the Gradio server
- Best for: quick wrapping of existing Gradio apps without code changes

### Approach C: Mount Both Together

- Use `gr.mount_gradio_app()` to serve Gradio UI + FastAPI REST on one server
- Best for: apps that need both GUI and API access simultaneously

## Conversion Workflow (Approach A — Extract Logic)

### Step 1: Analyze the Gradio App

Read the user's Gradio app and identify:

1. **Core functions** — the `fn` callbacks passed to `gr.Interface`, `gr.Button.click()`, etc.
2. **Input/output types** — map Gradio components to Pydantic models
3. **State management** — any `gr.State` usage needs to become server-side state
4. **File handling** — `gr.File`, `gr.Image` etc. become `UploadFile` in FastAPI

### Step 2: Create the Project Structure

```
todo-api/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app entry point
│   ├── routes/
│   │   ├── __init__.py
│   │   └── todos.py     # Route handlers
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py   # Pydantic request/response models
│   └── services/
│       ├── __init__.py
│       └── todo_service.py  # Core business logic (extracted from Gradio)
├── requirements.txt
└── README.md
```

### Step 3: Map Gradio Components to FastAPI

Reference the mapping table in `references/component-mapping.md` for detailed type conversions.

Quick reference:
| Gradio Component | FastAPI Equivalent |
|---|---|
| `gr.Textbox` | `str` body/query param |
| `gr.Number` | `int` or `float` param |
| `gr.Checkbox` | `bool` param |
| `gr.Dropdown` | `Literal[...]` or `Enum` |
| `gr.File` | `UploadFile` |
| `gr.Image` | `UploadFile` (image/\*) |
| `gr.Dataframe` | `list[dict]` |
| `gr.State` | Server-side session/DB |
| `gr.JSON` | `dict` or Pydantic model |

### Step 4: Extract and Wrap Functions

For each Gradio callback function:

1. **Copy the function** into `services/` as pure business logic (no Gradio imports)
2. **Create a Pydantic model** for its inputs and outputs
3. **Create a FastAPI route** that validates input, calls the service, returns the response

Example transformation:

**Before (Gradio):**

```python
import gradio as gr

todos = []

def add_todo(task: str):
    todos.append({"task": task, "done": False})
    return [[t["task"], t["done"]] for t in todos]

def toggle_todo(index: int):
    todos[index]["done"] = not todos[index]["done"]
    return [[t["task"], t["done"]] for t in todos]

demo = gr.Interface(fn=add_todo, inputs="text", outputs="dataframe")
demo.launch()
```

**After (FastAPI):**

```python
# app/services/todo_service.py
class TodoService:
    def __init__(self):
        self.todos = []

    def add(self, task: str) -> dict:
        todo = {"id": len(self.todos), "task": task, "done": False}
        self.todos.append(todo)
        return todo

    def toggle(self, todo_id: int) -> dict:
        self.todos[todo_id]["done"] = not self.todos[todo_id]["done"]
        return self.todos[todo_id]

    def list_all(self) -> list[dict]:
        return self.todos
```

```python
# app/models/schemas.py
from pydantic import BaseModel

class TodoCreate(BaseModel):
    task: str

class TodoResponse(BaseModel):
    id: int
    task: str
    done: bool
```

```python
# app/main.py
from fastapi import FastAPI
from app.routes import todos

app = FastAPI(title="Todo API")
app.include_router(todos.router, prefix="/api/v1")
```

```python
# app/routes/todos.py
from fastapi import APIRouter, HTTPException
from app.models.schemas import TodoCreate, TodoResponse
from app.services.todo_service import TodoService

router = APIRouter(tags=["todos"])
service = TodoService()

@router.post("/todos", response_model=TodoResponse)
def create_todo(body: TodoCreate):
    return service.add(body.task)

@router.get("/todos", response_model=list[TodoResponse])
def list_todos():
    return service.list_all()

@router.patch("/todos/{todo_id}/toggle", response_model=TodoResponse)
def toggle_todo(todo_id: int):
    try:
        return service.toggle(todo_id)
    except IndexError:
        raise HTTPException(status_code=404, detail="Todo not found")
```

### Step 5: Add Standard API Features

Always add these to the converted API:

- **CORS middleware** if the API will be called from browsers
- **Error handling** with proper HTTP status codes
- **API docs** — FastAPI gives you `/docs` (Swagger) and `/redoc` automatically
- **Health check endpoint** at `GET /health`

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}
```

### Step 6: Generate requirements.txt

```
fastapi>=0.100.0
uvicorn[standard]>=0.20.0
pydantic>=2.0.0
```

Do NOT include `gradio` in requirements unless using Approach B or C.

## Conversion Workflow (Approach B — gradio_client Proxy)

See `references/gradio-client-approach.md` for the full pattern.

Quick version:

```python
from fastapi import FastAPI
from gradio_client import Client

app = FastAPI()
gr_client = Client("http://localhost:7860")  # running Gradio app

@app.post("/api/todos")
def add_todo(task: str):
    result = gr_client.predict(task, api_name="/add_todo")
    return {"result": result}
```

## Conversion Workflow (Approach C — Mount Together)

```python
from fastapi import FastAPI
import gradio as gr

app = FastAPI()

# Your FastAPI REST endpoints
@app.get("/api/todos")
def list_todos():
    return service.list_all()

# Mount Gradio UI at /gui
demo = gr.Interface(...)
app = gr.mount_gradio_app(app, demo, path="/gui")
```

## Key Gotchas

1. **gr.State is not HTTP state** — Gradio's State component lives in-memory per session. For FastAPI, use a database, Redis, or at minimum an in-memory dict with session keys.
2. **File uploads differ** — Gradio handles temp files automatically. In FastAPI, you manage `UploadFile` objects explicitly.
3. **Streaming responses** — Gradio generators (`yield`) map to FastAPI `StreamingResponse`.
4. **Authentication** — Gradio's `auth=` parameter becomes FastAPI's dependency injection with OAuth2/JWT.
5. **Gradio's queue** — If the original app uses `demo.queue()`, the API might need background tasks (`BackgroundTasks`) or a task queue like Celery.
