"""AI UI — FastAPI API router.

Provides REST endpoints for:
  /api/ai-ui/requirements          — system requirements
  /api/ai-ui/plugins               — plugin CRUD + launch/stop
  /api/ai-ui/shell                 — shell command execution
  /api/ai-ui/gallery               — discover apps (future)
"""

import logging

from fastapi import APIRouter, HTTPException, Request, UploadFile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-ui", tags=["AI UI"])


# ─── System Requirements ─────────────────────────────────────────────────


@router.get("/requirements")
async def get_requirements():
    """Check all system requirements and return their status."""
    from pocketpaw.ai_ui.requirements import check_all_requirements

    requirements = await check_all_requirements()
    return {"requirements": requirements}


@router.post("/requirements/{req_id}/install")
async def install_requirement_endpoint(req_id: str):
    """Install a system requirement."""
    from pocketpaw.ai_ui.requirements import install_requirement

    try:
        result = await install_requirement(req_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("Requirement install failed: %s", req_id)
        raise HTTPException(status_code=500, detail=str(e))


# ─── Plugins ──────────────────────────────────────────────────────────────


@router.get("/plugins")
async def get_plugins():
    """List all installed plugins."""
    from pocketpaw.ai_ui.plugins import list_plugins

    return {"plugins": list_plugins()}


@router.get("/plugins/{plugin_id}")
async def get_plugin_detail(plugin_id: str):
    """Get detailed info about a plugin."""
    from pocketpaw.ai_ui.plugins import get_plugin

    plugin = get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    return {"plugin": plugin}


@router.get("/plugins/{plugin_id}/config")
async def get_plugin_config(plugin_id: str):
    """Get a plugin's config (env vars passed at launch)."""
    from pocketpaw.ai_ui.plugins import get_plugin_config as _get_config

    config = _get_config(plugin_id)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    return {"config": config}


@router.post("/plugins/{plugin_id}/chat")
async def chat_completion_proxy_endpoint(plugin_id: str, request: Request):
    """Proxy chat completion request to the plugin's /v1/chat/completions."""
    from pocketpaw.ai_ui.plugins import chat_completion_proxy as _proxy

    try:
        body = await request.json()
        messages = body.get("messages") or []
        if not messages:
            raise HTTPException(status_code=400, detail="messages required")
        result = _proxy(plugin_id, messages)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Chat proxy failed: %s", plugin_id)
        raise HTTPException(
            status_code=502,
            detail=str(e) or "Plugin chat unavailable",
        )


@router.get("/plugins/{plugin_id}/chat-history")
async def get_chat_history_endpoint(plugin_id: str):
    """Get persisted chat history for a plugin."""
    from pocketpaw.ai_ui.plugins import get_chat_history as _get

    try:
        messages = _get(plugin_id)
        return {"messages": messages}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/plugins/{plugin_id}/chat-history")
async def save_chat_history_endpoint(plugin_id: str, request: Request):
    """Save chat history for a plugin."""
    from pocketpaw.ai_ui.plugins import save_chat_history as _save

    try:
        body = await request.json()
        messages = body.get("messages") or []
        _save(plugin_id, messages)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/plugins/{plugin_id}/models")
async def get_plugin_models_endpoint(plugin_id: str, request: Request):
    """Fetch /v1/models from a running plugin.

    Returns { models: [...] }. Empty when plugin is not running.
    """
    from pocketpaw.ai_ui.plugins import fetch_plugin_models as _fetch

    host = request.query_params.get("host")
    port_str = request.query_params.get("port")
    port = int(port_str) if port_str is not None else None

    try:
        models = _fetch(plugin_id, host=host or None, port=port)
        return {"models": models}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/plugins/{plugin_id}/providers")
async def get_plugin_providers_endpoint(plugin_id: str, request: Request):
    """Fetch /v1/providers from a running plugin.

    Returns { providers: [...] }. Empty when plugin is not running.
    """
    from pocketpaw.ai_ui.plugins import fetch_plugin_providers as _fetch

    host = request.query_params.get("host")
    port_str = request.query_params.get("port")
    port = int(port_str) if port_str is not None else None

    try:
        providers = _fetch(plugin_id, host=host or None, port=port)
        return {"providers": providers}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/plugins/{plugin_id}/test-connection")
async def test_plugin_connection_endpoint(plugin_id: str, request: Request):
    """Ping the plugin's /health endpoint. Optional body: { host?, port? }."""
    from pocketpaw.ai_ui.plugins import test_plugin_connection as _test

    host = None
    port = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            host = body.get("host")
            port_val = body.get("port")
            if port_val is not None:
                port = int(port_val)
    except Exception:
        pass

    try:
        result = _test(plugin_id, host=host, port=port)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/plugins/{plugin_id}/codex/auth/status")
async def codex_auth_status_endpoint(plugin_id: str):
    """Return codex OAuth login status for AI Fast API."""
    from pocketpaw.ai_ui.plugins import get_codex_auth_status as _status

    if plugin_id != "ai-fast-api":
        raise HTTPException(status_code=400, detail="Codex OAuth is only available for ai-fast-api")
    return _status()


@router.post("/plugins/{plugin_id}/codex/auth/start")
async def codex_auth_start_endpoint(plugin_id: str):
    """Start codex device OAuth flow and return verification URL/code."""
    from pocketpaw.ai_ui.plugins import start_codex_device_auth as _start

    if plugin_id != "ai-fast-api":
        raise HTTPException(status_code=400, detail="Codex OAuth is only available for ai-fast-api")
    return _start()


@router.get("/plugins/{plugin_id}/codex/auth/poll")
async def codex_auth_poll_endpoint(plugin_id: str, session_id: str):
    """Poll a running codex OAuth device-auth session."""
    from pocketpaw.ai_ui.plugins import get_codex_device_auth_status as _poll

    if plugin_id != "ai-fast-api":
        raise HTTPException(status_code=400, detail="Codex OAuth is only available for ai-fast-api")
    return _poll(session_id)


@router.get("/plugins/{plugin_id}/qwen/auth/status")
async def qwen_auth_status_endpoint(plugin_id: str):
    """Return qwen OAuth login status for AI Fast API."""
    from pocketpaw.ai_ui.plugins import get_qwen_auth_status as _status

    if plugin_id != "ai-fast-api":
        raise HTTPException(status_code=400, detail="Qwen OAuth is only available for ai-fast-api")
    return _status()


@router.post("/plugins/{plugin_id}/qwen/auth/start")
async def qwen_auth_start_endpoint(plugin_id: str):
    """Start qwen device OAuth flow and return verification URL/code."""
    from pocketpaw.ai_ui.plugins import start_qwen_device_auth as _start

    if plugin_id != "ai-fast-api":
        raise HTTPException(status_code=400, detail="Qwen OAuth is only available for ai-fast-api")
    return _start()


@router.get("/plugins/{plugin_id}/qwen/auth/poll")
async def qwen_auth_poll_endpoint(plugin_id: str, session_id: str):
    """Poll a running qwen OAuth device-auth session."""
    from pocketpaw.ai_ui.plugins import get_qwen_device_auth_status as _poll

    if plugin_id != "ai-fast-api":
        raise HTTPException(status_code=400, detail="Qwen OAuth is only available for ai-fast-api")
    return _poll(session_id)


@router.get("/plugins/{plugin_id}/gemini/auth/status")
async def gemini_auth_status_endpoint(plugin_id: str):
    """Return gemini OAuth login status for AI Fast API."""
    from pocketpaw.ai_ui.plugins import get_gemini_auth_status as _status

    if plugin_id != "ai-fast-api":
        raise HTTPException(
            status_code=400, detail="Gemini OAuth is only available for ai-fast-api"
        )
    return _status()


@router.post("/plugins/{plugin_id}/gemini/auth/start")
async def gemini_auth_start_endpoint(plugin_id: str):
    """Start gemini OAuth flow and return session info."""
    from pocketpaw.ai_ui.plugins import start_gemini_device_auth as _start

    if plugin_id != "ai-fast-api":
        raise HTTPException(
            status_code=400, detail="Gemini OAuth is only available for ai-fast-api"
        )
    return _start()


@router.get("/plugins/{plugin_id}/gemini/auth/poll")
async def gemini_auth_poll_endpoint(plugin_id: str, session_id: str):
    """Poll a running gemini OAuth session."""
    from pocketpaw.ai_ui.plugins import get_gemini_device_auth_status as _poll

    if plugin_id != "ai-fast-api":
        raise HTTPException(
            status_code=400, detail="Gemini OAuth is only available for ai-fast-api"
        )
    return _poll(session_id)


@router.post("/plugins/{plugin_id}/ollama/local/setup")
async def setup_local_ollama_endpoint(plugin_id: str):
    """Install/start built-in local Ollama for AI Fast API local backend."""
    from pocketpaw.ai_ui.plugins import setup_local_ollama_for_ai_fast_api as _setup

    if plugin_id != "ai-fast-api":
        raise HTTPException(
            status_code=400, detail="Local Ollama setup is only available for ai-fast-api"
        )
    try:
        return await _setup()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("Local Ollama setup failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/plugins/{plugin_id}/config")
async def update_plugin_config_endpoint(plugin_id: str, request: Request):
    """Update a plugin's config (env vars). Restart required for changes to apply."""
    from pocketpaw.ai_ui.plugins import update_plugin_config as _update_config

    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Expected JSON object")
    # Accept { "config": { ... } } or flat { "KEY": "value" }
    raw = data.get("config", data)
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="Expected config object")
    config = {k: str(v) if v is not None else "" for k, v in raw.items()}
    try:
        result = _update_config(plugin_id, config)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/plugins/install")
async def install_plugin_endpoint(request: Request):
    """Install a plugin from a Git URL, local path, or uploaded .zip file."""
    from pocketpaw.ai_ui.plugins import install_plugin, install_plugin_from_zip

    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        file = form.get("file")
        if not isinstance(file, UploadFile) or file.filename == "":
            raise HTTPException(status_code=400, detail="No file provided. Upload a .zip plugin.")
        if not (file.filename or "").lower().endswith(".zip"):
            raise HTTPException(
                status_code=400,
                detail="Please upload a .zip file containing a PocketPaw plugin.",
            )
        zip_bytes = await file.read()
        if len(zip_bytes) > 100 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Zip file too large (max 100MB).")
        try:
            result = await install_plugin_from_zip(zip_bytes)
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.exception("Plugin install from zip failed")
            raise HTTPException(status_code=500, detail=str(e))

    data = await request.json()
    source = data.get("source", "").strip()
    if not source:
        raise HTTPException(status_code=400, detail="Missing 'source' field")

    try:
        result = await install_plugin(source)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("Plugin install failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/plugins/{plugin_id}/launch")
async def launch_plugin_endpoint(plugin_id: str):
    """Launch a plugin."""
    from pocketpaw.ai_ui.plugins import launch_plugin

    try:
        result = await launch_plugin(plugin_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Plugin launch failed: %s", plugin_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/plugins/{plugin_id}/stop")
async def stop_plugin_endpoint(plugin_id: str):
    """Stop a running plugin."""
    from pocketpaw.ai_ui.plugins import stop_plugin

    try:
        result = await stop_plugin(plugin_id)
        return result
    except Exception as e:
        logger.exception("Plugin stop failed: %s", plugin_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/plugins/{plugin_id}")
async def remove_plugin_endpoint(plugin_id: str):
    """Remove a plugin."""
    from pocketpaw.ai_ui.plugins import remove_plugin

    try:
        result = remove_plugin(plugin_id)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Plugin remove failed: %s", plugin_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/plugins/{plugin_id}/logs")
async def get_plugin_logs(plugin_id: str):
    """Get recent logs for a running plugin."""
    from pocketpaw.ai_ui.plugins import get_plugins_dir

    log_path = get_plugins_dir() / plugin_id / ".pocketpaw.log"
    if not log_path.exists():
        return {"logs": [], "plugin_id": plugin_id}

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        lines = text.strip().splitlines()[-200:]
        return {"logs": lines, "plugin_id": plugin_id}
    except OSError:
        return {"logs": [], "plugin_id": plugin_id}


@router.get("/plugins/{plugin_id}/docs", include_in_schema=False)
async def plugin_swagger(plugin_id: str):
    """Serve API docs for a plugin.

    When the plugin is **running** and exposes a port, we load the live
    OpenAPI spec straight from the running FastAPI server — this always
    reflects the real routes, models, and parameters.

    When the plugin is **stopped**, we fall back to the static
    ``openapi.json`` that was generated at install time.
    """
    import json as _json

    from fastapi.responses import HTMLResponse

    from pocketpaw.ai_ui.plugins import _is_plugin_running, get_plugins_dir

    plugins_dir = get_plugins_dir()
    plugin_path = plugins_dir / plugin_id
    manifest_path = plugin_path / "pocketpaw.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Plugin not found")

    manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
    port = manifest.get("port")
    title = f"Plugin API: {manifest.get('name', plugin_id)}"
    running = port and _is_plugin_running(plugin_id, plugin_path)

    if running:
        spec_url = f"http://localhost:{port}/openapi.json"
        html = f"""\
<!DOCTYPE html>
<html>
<head>
<title>{title}</title>
<meta charset="utf-8"/>
<link rel="stylesheet"
      href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
<style>body {{ margin: 0; }} .swagger-ui .topbar {{ display: none; }}</style>
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
SwaggerUIBundle({{
    url: '{spec_url}',
    dom_id: '#swagger-ui',
    presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
    layout: 'BaseLayout',
    validatorUrl: null,
    persistAuthorization: true
}});
</script>
</body>
</html>"""
        return HTMLResponse(content=html)

    openapi_file = manifest.get("openapi")
    if not openapi_file:
        raise HTTPException(
            status_code=404, detail="Plugin has no OpenAPI spec (start the plugin to generate one)"
        )

    spec_path = plugin_path / openapi_file
    if not spec_path.exists():
        raise HTTPException(
            status_code=404,
            detail="OpenAPI spec not found — start and stop the plugin once to generate it",
        )

    spec_json = spec_path.read_text(encoding="utf-8")

    html = f"""\
<!DOCTYPE html>
<html>
<head>
<title>{title} (offline)</title>
<meta charset="utf-8"/>
<link rel="stylesheet"
      href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
<style>body {{ margin: 0; }} .swagger-ui .topbar {{ display: none; }}</style>
</head>
<body>
<div style="background:#fffbe6;color:#856404;padding:8px 16px;font-size:13px;
            border-bottom:1px solid #ffc107;font-family:sans-serif">
  Plugin is stopped — showing spec from last install. Start the plugin for live docs.
</div>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
var spec = {spec_json};
spec.servers = [{{ url: 'http://localhost:{port or 8000}', description: 'Local plugin server' }}];
SwaggerUIBundle({{
    spec: spec,
    dom_id: '#swagger-ui',
    presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
    layout: 'BaseLayout',
    validatorUrl: null,
    persistAuthorization: true
}});
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/plugins/{plugin_id}/{filename:path}")
async def serve_plugin_file(plugin_id: str, filename: str):
    """Serve arbitrary files from the plugin's directory (e.g. openapi.json)."""
    from fastapi.responses import FileResponse

    from pocketpaw.ai_ui.plugins import get_plugins_dir

    plugins_dir = get_plugins_dir()
    plugin_path = plugins_dir / plugin_id
    if not plugin_path.exists():
        raise HTTPException(status_code=404, detail="Plugin not found")

    file_path = (plugin_path / filename).resolve()
    # Security check to prevent directory traversal
    if not str(file_path).startswith(str(plugin_path)):
        raise HTTPException(status_code=403, detail="Forbidden path traversal")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path)


# ─── Shell ────────────────────────────────────────────────────────────────


@router.post("/shell")
async def shell_endpoint(request: Request):
    """Execute a shell command."""
    from pocketpaw.ai_ui.plugins import run_shell

    data = await request.json()
    command = data.get("command", "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="Missing 'command' field")

    cwd = data.get("cwd")
    result = await run_shell(command, cwd=cwd)
    return result


# ─── Gallery / Discover ───────────────────────────────────────────────────


@router.get("/gallery")
async def get_gallery():
    """Get discovery gallery of curated built-in apps."""
    from pocketpaw.ai_ui import builtins as ai_ui_builtins

    apps = []
    for app in ai_ui_builtins.get_gallery():
        item = dict(app)
        app_id = str(item.get("id", ""))
        reason = ai_ui_builtins.get_install_block_reason(app_id) if app_id else None
        item["install_disabled"] = bool(reason)
        if reason:
            item["install_disabled_reason"] = reason
        apps.append(item)

    return {"apps": apps}
