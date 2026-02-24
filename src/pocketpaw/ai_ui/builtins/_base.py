"""Base protocol for builtin app definitions.

Every module in the builtins package must expose a ``DEFINITION`` dict that
conforms to the ``BuiltinDefinition`` shape below.  The ``__init__`` module
auto-discovers all sibling modules and builds a registry from them.
"""

from __future__ import annotations

from typing import TypedDict


class GalleryEntry(TypedDict, total=False):
    id: str
    name: str
    description: str
    icon: str
    source: str
    stars: str
    category: str


class BuiltinDefinition(TypedDict, total=False):
    """Shape every builtin module's ``DEFINITION`` must follow.

    Exactly one of ``files``, ``git_source``, or ``source_dir`` is required:
      - ``files``      → inline files written directly to the plugin dir.
      - ``git_source`` → git URL cloned into the plugin dir; an overlay
                         ``pocketpaw.json`` is generated from ``manifest``.
      - ``source_dir`` → absolute path to a local directory whose contents
                         are copied into the plugin dir (offline, no network).
    """

    id: str
    manifest: dict
    files: dict[str, str]
    git_source: str
    source_dir: str
    gallery: GalleryEntry
