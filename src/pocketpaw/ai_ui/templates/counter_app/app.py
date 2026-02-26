from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="PocketPaw Counter App", version="1.0.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """<!doctype html>
<html>
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
    <title>Counter App</title>
    <style>
      body { font-family: ui-sans-serif, system-ui; display:flex; align-items:center; justify-content:center; min-height:100vh; background:#0f172a; color:#e2e8f0; }
      .card { background:#111827; border:1px solid #334155; border-radius:16px; padding:24px; text-align:center; width:320px; }
      h1 { margin:0 0 12px 0; font-size:20px; }
      #value { font-size:48px; font-weight:700; margin:12px 0 18px 0; }
      button { margin:0 6px; padding:10px 14px; border-radius:10px; border:1px solid #475569; background:#1f2937; color:#e2e8f0; cursor:pointer; }
      button:hover { background:#334155; }
    </style>
  </head>
  <body>
    <div class=\"card\">
      <h1>Counter App</h1>
      <div id=\"value\">0</div>
      <button onclick=\"dec()\">-1</button>
      <button onclick=\"inc()\">+1</button>
      <button onclick=\"resetCount()\">Reset</button>
    </div>
    <script>
      let n = 0;
      const el = document.getElementById('value');
      function draw(){ el.textContent = String(n); }
      function inc(){ n += 1; draw(); }
      function dec(){ n -= 1; draw(); }
      function resetCount(){ n = 0; draw(); }
      draw();
    </script>
  </body>
</html>"""
