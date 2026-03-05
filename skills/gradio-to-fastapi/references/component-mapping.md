# Gradio Component to FastAPI Type Mapping

## Input Components

| Gradio Component | Python Type | FastAPI Parameter | Pydantic Field | Notes |
|---|---|---|---|---|
| `gr.Textbox()` | `str` | `Body(...)` or `Query(...)` | `Field(...)` | Use Query for GET, Body for POST |
| `gr.Number()` | `int \| float` | `Body(...)` or `Query(...)` | `Field(ge=0)` | Add constraints as needed |
| `gr.Slider(min=0, max=100)` | `float` | `Body(...)` | `Field(ge=0, le=100)` | Map min/max to ge/le |
| `gr.Checkbox()` | `bool` | `Body(...)` or `Query(False)` | `Field(default=False)` | |
| `gr.Radio(choices=[...])` | `Literal[...]` | `Body(...)` | Use `Enum` class | |
| `gr.Dropdown(choices=[...])` | `Literal[...]` | `Query(...)` | Use `Enum` class | |
| `gr.File()` | `UploadFile` | `File(...)` | N/A (use `Form`) | Needs `python-multipart` |
| `gr.Image(type="pil")` | `UploadFile` | `File(...)` | N/A | Accept image/* content types |
| `gr.Image(type="filepath")` | `UploadFile` | `File(...)` | N/A | Save to temp then pass path |
| `gr.Audio()` | `UploadFile` | `File(...)` | N/A | Accept audio/* content types |
| `gr.Video()` | `UploadFile` | `File(...)` | N/A | Accept video/* content types |
| `gr.Dataframe()` | `list[dict]` | `Body(...)` | `list[RowModel]` | Define a row Pydantic model |
| `gr.JSON()` | `dict \| list` | `Body(...)` | Pydantic model | Strongly type if possible |
| `gr.ColorPicker()` | `str` | `Body(...)` | `Field(pattern=r"^#[0-9a-fA-F]{6}$")` | Hex color string |
| `gr.DateTime()` | `datetime` | `Body(...)` | `Field(...)` | Use `datetime.datetime` |

## Output Components

| Gradio Component | FastAPI Response | Notes |
|---|---|---|
| `gr.Textbox()` | `str` in JSON | Direct return |
| `gr.Number()` | `int \| float` in JSON | Direct return |
| `gr.JSON()` | `JSONResponse` | Default FastAPI behavior |
| `gr.Dataframe()` | `list[dict]` in JSON | Return list of row objects |
| `gr.Image()` | `FileResponse` or base64 in JSON | Use `StreamingResponse` for dynamic |
| `gr.File()` | `FileResponse` | Set correct content-type header |
| `gr.Audio()` | `FileResponse` | Stream for large files |
| `gr.Video()` | `StreamingResponse` | Always stream video |
| `gr.Plot()` | Base64 PNG in JSON or HTML | Generate plot, encode, return |
| `gr.HTML()` | `HTMLResponse` | Use `fastapi.responses.HTMLResponse` |
| `gr.Markdown()` | `str` in JSON | Return raw markdown string |

## State Management

| Gradio Pattern | FastAPI Equivalent |
|---|---|
| `gr.State(initial_value)` | Database / Redis / in-memory dict |
| Session-specific state | Session middleware or JWT tokens |
| Global state (module-level) | App-level dependency or singleton service |
| `gr.State` with lists/dicts | Database table or Redis hash |

### Example: Converting gr.State

**Gradio:**
```python
def add_item(item, state):
    state.append(item)
    return state, state

demo = gr.Interface(
    fn=add_item,
    inputs=["text", gr.State([])],
    outputs=["json", gr.State()]
)
```

**FastAPI (in-memory per-session):**
```python
from fastapi import Depends, Header
from uuid import uuid4

sessions: dict[str, list] = {}

def get_session(x_session_id: str = Header(default=None)):
    if not x_session_id:
        x_session_id = str(uuid4())
    if x_session_id not in sessions:
        sessions[x_session_id] = []
    return x_session_id, sessions[x_session_id]

@app.post("/items")
def add_item(item: str, session=Depends(get_session)):
    session_id, state = session
    state.append(item)
    return {"session_id": session_id, "items": state}
```

## File Upload Patterns

**Gradio:**
```python
def process_file(file):
    # file is a temp filepath string
    with open(file, "r") as f:
        return f.read()
```

**FastAPI:**
```python
from fastapi import UploadFile, File

@app.post("/upload")
async def process_file(file: UploadFile = File(...)):
    contents = await file.read()
    return {"filename": file.filename, "size": len(contents)}
```

## Streaming / Generator Patterns

**Gradio (yield-based):**
```python
def generate_text(prompt):
    for word in slow_generator(prompt):
        yield word
```

**FastAPI (StreamingResponse):**
```python
from fastapi.responses import StreamingResponse

@app.post("/generate")
def generate_text(prompt: str):
    def stream():
        for word in slow_generator(prompt):
            yield word
    return StreamingResponse(stream(), media_type="text/plain")
```

## Authentication Mapping

| Gradio Auth | FastAPI Auth |
|---|---|
| `demo.launch(auth=("user","pass"))` | HTTP Basic Auth dependency |
| `demo.launch(auth=check_fn)` | Custom auth dependency |
| `auth_dependency` on mount | OAuth2 / JWT middleware |
