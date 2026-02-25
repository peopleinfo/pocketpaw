"""AI UI — FastAPI API router.

Provides REST endpoints for:
  /api/ai-ui/requirements          — system requirements
  /api/ai-ui/plugins               — plugin CRUD + launch/stop
  /api/ai-ui/shell                 — shell command execution
  /api/ai-ui/gallery               — discover apps (future)
"""

import logging

from fastapi import APIRouter, HTTPException, Request

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


@router.post("/plugins/install")
async def install_plugin_endpoint(request: Request):
    """Install a plugin from a Git URL, local path, or uploaded .zip file."""
    from pocketpaw.ai_ui.plugins import install_plugin, install_plugin_from_zip

    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        file = form.get("file")
        if not file or file.filename == "":
            raise HTTPException(
                status_code=400, detail="No file provided. Upload a .zip plugin."
            )
        if not (file.filename or "").lower().endswith(".zip"):
            raise HTTPException(
                status_code=400,
                detail="Please upload a .zip file containing a PocketPaw plugin.",
            )
        zip_bytes = await file.read()
        if len(zip_bytes) > 100 * 1024 * 1024:
            raise HTTPException(
                status_code=400, detail="Zip file too large (max 100MB)."
            )
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

    from pocketpaw.ai_ui.plugins import get_plugins_dir, _is_plugin_running

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
    from pocketpaw.ai_ui.plugins import get_plugins_dir
    from fastapi.responses import FileResponse
    
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
    from pocketpaw.ai_ui.builtins import get_gallery as builtin_gallery

    return {"apps": builtin_gallery()}
