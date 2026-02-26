"""Built-in: G4F Chat template (standalone g4f GUI)."""

from pathlib import Path

from pocketpaw.ai_ui.builtins._base import BuiltinDefinition

_SOURCE_DIR = Path(__file__).resolve().parents[1] / "templates" / "g4f_chat"

_MANIFEST = {
    "name": "Gf4 Chat",
    "description": (
        "Standalone g4f web chat UI template. "
        "Installs g4f[gui] and serves /chat in AI UI."
    ),
    "icon": "message-circle",
    "version": "1.0.0",
    "start": "bash start.sh",
    "install": "bash install.sh",
    "requires": ["uv", "python"],
    "port": 8080,
    "web_view": "iframe",
    "web_view_path": "/chat/",
    "env": {
        "PORT": "8080",
        "HOST": "0.0.0.0",
    },
}

DEFINITION: BuiltinDefinition = {
    "id": "g4f-chat-template",
    "manifest": _MANIFEST,
    "source_dir": str(_SOURCE_DIR),
    "files": {},
    "gallery": {
        "id": "g4f-chat-template",
        "name": "Gf4 Chat (Template)",
        "description": (
            "One-click template for the official g4f GUI chat page. "
            "Runs locally and opens directly at /chat/."
        ),
        "icon": "message-circle",
        "source": "builtin:g4f-chat-template",
        "stars": "GUI Chat",
        "category": "Template",
    },
}
