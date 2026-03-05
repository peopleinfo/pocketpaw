---
name: gradio-client-integration
description: Call any Gradio app programmatically from Python server code using the gradio_client library. Use this skill when the user wants to consume a Gradio app as a backend service, call Gradio endpoints from a script or server, automate interactions with a Gradio app, use Hugging Face Spaces as APIs, build a backend that talks to a running Gradio server, integrate Gradio predictions into a pipeline, or use gradio_client in any project. Triggers on mentions of "gradio_client", "gradio client", "call gradio from code", "gradio predict", "gradio api", "use gradio as backend", "huggingface space api".
user-invocable: true
argument-hint: "<gradio_url_or_space> [endpoint_name]"
allowed-tools:
  - read_file
  - write_file
  - shell
---

# Gradio Client Integration Skill

This skill teaches how to call any Gradio app programmatically using `gradio_client`, treating Gradio as a backend service rather than a GUI.

## Core Concept

Every Gradio app automatically exposes API endpoints. The `gradio_client` library lets you call these endpoints from any Python code — scripts, servers, pipelines, cron jobs, etc. — without ever opening a browser.

## Quick Start Pattern

```python
from gradio_client import Client

# Connect to a local Gradio app
client = Client("http://localhost:7860")

# Or connect to a Hugging Face Space
client = Client("username/space-name")

# Discover available endpoints
client.view_api()

# Call an endpoint
result = client.predict("input_value", api_name="/endpoint_name")
```

## Step-by-Step Workflow

### Step 1: Discover Available Endpoints

Always start by inspecting what endpoints the Gradio app exposes:

```python
from gradio_client import Client

client = Client("http://localhost:7860")
info = client.view_api(return_format="dict")
print(info)
```

This returns details about every endpoint including:

- `api_name` — the endpoint path (e.g., `/predict`, `/add_todo`)
- Parameter names and types
- Return types

### Step 2: Call Endpoints

**Simple call (blocking):**

```python
result = client.predict(
    "Hello world",          # positional arg matching Gradio input order
    api_name="/predict"
)
```

**With keyword arguments (recommended):**

```python
result = client.predict(
    text="Hello world",
    temperature=0.7,
    api_name="/generate"
)
```

**Background call (non-blocking):**

```python
job = client.submit("Hello world", api_name="/predict")

# Check status
print(job.status())

# Get result when ready (blocks until done)
result = job.result(timeout=60)
```

### Step 3: Handle Different Input Types

**Text / Numbers / Booleans:** Pass directly as Python values.

**Files:** Use `handle_file()` for file inputs:

```python
from gradio_client import Client, handle_file

client = Client("username/whisper")
result = client.predict(
    audio=handle_file("recording.wav"),
    api_name="/transcribe"
)
```

`handle_file()` accepts:

- Local file paths: `handle_file("/path/to/file.png")`
- URLs: `handle_file("https://example.com/image.jpg")`

**Dataframes:** Pass as list of lists or dict format:

```python
data = [["Alice", 30], ["Bob", 25]]
result = client.predict(data, api_name="/process_data")
```

### Step 4: Handle Outputs

Outputs match the Gradio component types:

```python
# Single output
text_result = client.predict("input", api_name="/predict")
# text_result is a string

# Multiple outputs — returns a tuple
result = client.predict("input", api_name="/analyze")
summary, score, data = result

# File outputs — returns local filepath
filepath = client.predict(
    handle_file("image.png"),
    api_name="/upscale"
)
# filepath is a string path to the downloaded file
```

### Step 5: Integrate into Your Server

**FastAPI integration:**

```python
from fastapi import FastAPI
from gradio_client import Client

app = FastAPI()
gr_client = Client("http://localhost:7860")

@app.post("/api/predict")
def predict(text: str):
    result = gr_client.predict(text, api_name="/predict")
    return {"result": result}
```

**Flask integration:**

```python
from flask import Flask, request, jsonify
from gradio_client import Client

app = Flask(__name__)
gr_client = Client("http://localhost:7860")

@app.route("/api/predict", methods=["POST"])
def predict():
    text = request.json["text"]
    result = gr_client.predict(text, api_name="/predict")
    return jsonify({"result": result})
```

**Script / Pipeline:**

```python
from gradio_client import Client, handle_file
import glob

client = Client("username/image-classifier")

for img_path in glob.glob("images/*.jpg"):
    label = client.predict(
        image=handle_file(img_path),
        api_name="/classify"
    )
    print(f"{img_path}: {label}")
```

## Connection Options

```python
# Local Gradio app
client = Client("http://localhost:7860")

# Hugging Face Space (public)
client = Client("username/space-name")

# Hugging Face Space (private)
client = Client("username/private-space", hf_token="hf_xxxxx")

# Gradio share link
client = Client("https://abc123.gradio.live")

# With custom headers
client = Client("http://localhost:7860", headers={"Authorization": "Bearer token"})

# Skip SSL verification (self-signed certs)
client = Client("https://myserver.local:7860", ssl_verify=False)
```

## Making Your Gradio App API-Friendly

When building a Gradio app that will also be called via `gradio_client`, follow these practices:

### Name Your Endpoints

```python
# Good — named endpoints are easy to call
btn.click(add_todo, inputs=task, outputs=table, api_name="add_todo")

# The client calls it as:
# client.predict("task text", api_name="/add_todo")
```

### Use `gr.api()` for API-Only Endpoints

```python
import gradio as gr

with gr.Blocks() as demo:
    # ... UI components ...

    # API-only endpoint (no UI component needed)
    def search(query: str, limit: int = 10) -> list[dict]:
        return db.search(query, limit)

    gr.api(search, api_name="search")
```

### Control Visibility

```python
# Public: shown in API docs, callable
btn.click(fn, inputs, outputs, api_name="public_fn", api_visibility="public")

# Undocumented: hidden from docs but still callable
btn.click(fn, inputs, outputs, api_name="internal_fn", api_visibility="undocumented")

# Private: completely disabled for API access
btn.click(fn, inputs, outputs, api_visibility="private")
```

## Error Handling

```python
from gradio_client import Client
import httpx

client = Client("http://localhost:7860")

try:
    result = client.predict("input", api_name="/predict")
except httpx.ConnectError:
    print("Gradio app is not running")
except Exception as e:
    if "queue is full" in str(e).lower():
        print("App is overloaded, retry later")
    else:
        print(f"Prediction failed: {e}")
```

## Performance Tips

1. **Reuse the Client instance** — don't create a new `Client()` per request
2. **Use `.submit()` for concurrent calls** — it runs in background threads
3. **Set timeouts** on `.result(timeout=30)` to avoid hanging
4. **Duplicate private Spaces** if you hit rate limits on public ones
5. **Run Gradio with `demo.queue()`** for handling concurrent requests

```python
# Concurrent calls using submit
jobs = []
for text in texts:
    job = client.submit(text, api_name="/predict")
    jobs.append(job)

results = [job.result(timeout=60) for job in jobs]
```

## Requirements

```
gradio-client>=1.0.0
```

Note: You do NOT need to install the full `gradio` package — `gradio_client` is a lightweight standalone library.
