"""Built-in: Counter App template for quick AI UI validation."""

from pathlib import Path

from pocketpaw.ai_ui.builtins._base import BuiltinDefinition

_SOURCE_DIR = Path(__file__).resolve().parents[1] / "templates" / "counter_app"

_MANIFEST = {
    "name": "Counter App",
    "description": "Minimal FastAPI counter app template for AI UI plugin testing.",
    "icon": "hash",
    "version": "1.0.0",
    "start": "bash start.sh",
    "install": "bash install.sh",
    "requires": ["python"],
    "port": 8000,
    "web_view": "iframe",
    "web_view_path": "/",
    "env": {
        "PORT": "8000",
    },
}

DEFINITION: BuiltinDefinition = {
    "id": "counter-template",
    "manifest": _MANIFEST,
    "source_dir": str(_SOURCE_DIR),
    "files": {},
    "gallery": {
        "id": "counter-template",
        "name": "Counter App (Template)",
        "description": (
            "Tiny starter plugin with FastAPI + HTML UI so you can "
            "verify AI UI install/launch quickly."
        ),
        "icon": "hash",
        "source": "builtin:counter-template",
        "stars": "Starter",
        "category": "Template",
    },
}
