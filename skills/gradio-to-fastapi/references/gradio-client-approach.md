# Gradio Client Proxy Approach

Use this approach when you want to keep the Gradio app running as-is and wrap it with a FastAPI REST API. The FastAPI app acts as a thin proxy that translates REST requests into Gradio client calls.

## When to Use This

- You don't want to modify the existing Gradio app
- The Gradio app is hosted remotely (e.g., Hugging Face Spaces)
- You need a quick REST wrapper without refactoring
- The Gradio app has complex internal state you don't want to replicate

## Project Structure

```
todo-api/
├── main.py
├── requirements.txt
└── README.md
```

## Full Example: Todo App Proxy

### The Existing Gradio App (don't modify this)

```python
# gradio_app.py — the original app, running on port 7860
import gradio as gr

todos = []

def add_todo(task: str):
    todos.append({"task": task, "done": False})
    return format_todos()

def toggle_todo(index: int):
    if 0 <= index < len(todos):
        todos[index]["done"] = not todos[index]["done"]
    return format_todos()

def delete_todo(index: int):
    if 0 <= index < len(todos):
        todos.pop(index)
    return format_todos()

def list_todos():
    return format_todos()

def format_todos():
    return [[i, t["task"], t["done"]] for i, t in enumerate(todos)]

with gr.Blocks() as demo:
    task_input = gr.Textbox(label="Task")
    add_btn = gr.Button("Add")
    index_input = gr.Number(label="Index", precision=0)
    toggle_btn = gr.Button("Toggle")
    delete_btn = gr.Button("Delete")
    output = gr.Dataframe(headers=["#", "Task", "Done"])

    add_btn.click(add_todo, inputs=task_input, outputs=output, api_name="add_todo")
    toggle_btn.click(toggle_todo, inputs=index_input, outputs=output, api_name="toggle_todo")
    delete_btn.click(delete_todo, inputs=index_input, outputs=output, api_name="delete_todo")
    demo.load(list_todos, outputs=output, api_name="list_todos")

demo.launch(server_port=7860)
```

### The FastAPI Proxy (new project: todo-api)

```python
# main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from gradio_client import Client

app = FastAPI(
    title="Todo API",
    description="REST API proxy for Gradio Todo app",
    version="1.0.0"
)

# Connect to the running Gradio app
GRADIO_URL = "http://localhost:7860"
gr_client = Client(GRADIO_URL)


class TodoCreate(BaseModel):
    task: str

class TodoToggle(BaseModel):
    index: int

class TodoDelete(BaseModel):
    index: int


@app.get("/health")
def health():
    return {"status": "ok", "gradio_url": GRADIO_URL}


@app.get("/api/todos")
def list_todos():
    """List all todos from the Gradio app."""
    try:
        result = gr_client.predict(api_name="/list_todos")
        return {"todos": _parse_dataframe(result)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gradio app error: {str(e)}")


@app.post("/api/todos")
def add_todo(body: TodoCreate):
    """Add a new todo via the Gradio app."""
    try:
        result = gr_client.predict(body.task, api_name="/add_todo")
        return {"todos": _parse_dataframe(result)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gradio app error: {str(e)}")


@app.patch("/api/todos/toggle")
def toggle_todo(body: TodoToggle):
    """Toggle a todo's done status via the Gradio app."""
    try:
        result = gr_client.predict(body.index, api_name="/toggle_todo")
        return {"todos": _parse_dataframe(result)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gradio app error: {str(e)}")


@app.delete("/api/todos/{index}")
def delete_todo(index: int):
    """Delete a todo via the Gradio app."""
    try:
        result = gr_client.predict(index, api_name="/delete_todo")
        return {"todos": _parse_dataframe(result)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gradio app error: {str(e)}")


def _parse_dataframe(result):
    """Parse Gradio dataframe output into list of dicts."""
    if isinstance(result, dict) and "data" in result:
        rows = result["data"]
    elif isinstance(result, list):
        rows = result
    else:
        return result

    todos = []
    for row in rows:
        if len(row) >= 3:
            todos.append({
                "index": row[0],
                "task": row[1],
                "done": row[2]
            })
    return todos
```

### requirements.txt

```
fastapi>=0.100.0
uvicorn[standard]>=0.20.0
gradio-client>=1.0.0
pydantic>=2.0.0
```

### Running Both

```bash
# Terminal 1: Start the Gradio app
python gradio_app.py

# Terminal 2: Start the FastAPI proxy
uvicorn main:app --port 8000 --reload
```

### Testing

```bash
# List todos
curl http://localhost:8000/api/todos

# Add a todo
curl -X POST http://localhost:8000/api/todos \
  -H "Content-Type: application/json" \
  -d '{"task": "Buy groceries"}'

# Toggle todo at index 0
curl -X PATCH http://localhost:8000/api/todos/toggle \
  -H "Content-Type: application/json" \
  -d '{"index": 0}'

# Delete todo at index 0
curl -X DELETE http://localhost:8000/api/todos/0
```

## Discovering Gradio API Endpoints

Before building the proxy, discover what endpoints the Gradio app exposes:

```python
from gradio_client import Client

client = Client("http://localhost:7860")
client.view_api()
```

This prints all available `api_name` endpoints with their parameter types.

## Error Handling Best Practices

1. **Always wrap `gr_client.predict()` in try/except** — the Gradio app might be down
2. **Use HTTP 502 (Bad Gateway)** when the Gradio app fails — your API is a proxy
3. **Add timeouts** — Gradio calls can be slow if the app is queued
4. **Health check should verify Gradio connectivity**

```python
@app.get("/health")
def health():
    try:
        gr_client.predict(api_name="/list_todos")
        return {"status": "ok", "gradio": "connected"}
    except:
        return {"status": "degraded", "gradio": "disconnected"}
```

## Using with Remote Gradio Apps (Hugging Face Spaces)

```python
# Connect to a Hugging Face Space
gr_client = Client("username/space-name")

# With authentication for private spaces
gr_client = Client("username/private-space", hf_token="hf_...")
```

## Async Support

For better performance under load, use the async submit pattern:

```python
@app.post("/api/todos")
async def add_todo(body: TodoCreate):
    job = gr_client.submit(body.task, api_name="/add_todo")
    result = job.result(timeout=30)
    return {"todos": _parse_dataframe(result)}
```
