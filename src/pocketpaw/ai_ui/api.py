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
    """Install a plugin from a Git URL or local path."""
    from pocketpaw.ai_ui.plugins import install_plugin

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
    """Get recent logs for a running plugin (stub for now)."""
    return {"logs": [], "plugin_id": plugin_id}


@router.get("/plugins/{plugin_id}/docs", include_in_schema=False)
async def plugin_swagger(plugin_id: str):
    """Render a Swagger UI iframe pointing at a specific plugin's OpenAPI JSON."""
    from fastapi.openapi.docs import get_swagger_ui_html
    return get_swagger_ui_html(
        openapi_url=f"/api/ai-ui/plugins/{plugin_id}/openapi.json",
        title=f"Plugin API: {plugin_id}"
    )

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
    gallery = [
        {
            "id": "ollama",
            "name": "Ollama (Built-in)",
            "description": "Run open-source LLMs locally — Llama, Mistral, Phi, and more. Self-contained 1-click install.",
            "icon": "brain",
            "source": "builtin:ollama",
            "stars": "Native Wrapper",
            "category": "Curated / Built-in",
        }
    ]
    return {"apps": gallery}
