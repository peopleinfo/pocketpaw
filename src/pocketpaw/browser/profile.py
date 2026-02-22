# Browser profile management for anti-detect sessions.
"""Profile CRUD and JSON-backed persistence for anti-detect browser profiles.

Each profile has its own user_data_dir for persistent cookies/localStorage,
a stored fingerprint, and configuration for proxy / OS / browser plugin.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default storage locations
_PROFILES_DIR = Path.home() / ".pocketpaw" / "browser_profiles"
_PROFILES_JSON = _PROFILES_DIR / "profiles.json"


@dataclass
class BrowserProfile:
    """Represents an anti-detect browser profile."""

    id: str
    name: str
    status: str = "IDLE"  # IDLE | RUNNING | ERROR
    proxy: str = ""
    start_url: str = ""
    os_type: str = "macos"  # macos | windows | linux
    browser_type: str = "chromium"  # chromium | firefox
    plugin: str = "playwright"  # playwright | camoufox
    fingerprint: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    last_used_at: str = ""
    notes: str = ""

    @property
    def user_data_dir(self) -> Path:
        """Per-profile persistent browser data directory."""
        return _PROFILES_DIR / "data" / self.id

    def touch(self) -> None:
        """Update last used timestamp."""
        self.last_used_at = datetime.now(tz=UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Serialise to dict for JSON/API responses."""
        d = asdict(self)
        d["user_data_dir"] = str(self.user_data_dir)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BrowserProfile:
        """Create a profile from a dict (ignores unknown keys)."""
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


class ProfileStore:
    """JSON-file-backed store for browser profiles.

    Profiles persisted at ``~/.pocketpaw/browser_profiles/profiles.json``.
    Each profile also has a user data directory at ``data/<id>/``.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _PROFILES_JSON
        self._profiles: dict[str, BrowserProfile] = {}
        self._load()

    # ── CRUD ──────────────────────────────────────────────────────

    def list(self) -> list[BrowserProfile]:
        """Return all profiles, newest first."""
        return sorted(self._profiles.values(), key=lambda p: p.created_at, reverse=True)

    def get(self, profile_id: str) -> BrowserProfile | None:
        """Get a profile by ID."""
        return self._profiles.get(profile_id)

    def get_by_name(self, name: str) -> BrowserProfile | None:
        """Find a profile by name (case-insensitive)."""
        name_lower = name.lower()
        for p in self._profiles.values():
            if p.name.lower() == name_lower:
                return p
        return None

    def create(
        self,
        name: str,
        *,
        start_url: str = "",
        proxy: str = "",
        os_type: str = "macos",
        browser_type: str = "chromium",
        plugin: str = "playwright",
        notes: str = "",
    ) -> BrowserProfile:
        """Create a new profile and persist it."""
        profile = BrowserProfile(
            id=uuid.uuid4().hex[:12],
            name=name,
            start_url=start_url,
            proxy=proxy,
            os_type=os_type,
            browser_type=browser_type,
            plugin=plugin,
            notes=notes,
        )
        # Ensure user data dir exists
        profile.user_data_dir.mkdir(parents=True, exist_ok=True)
        self._profiles[profile.id] = profile
        self._save()
        logger.info("Created browser profile '%s' (id=%s)", name, profile.id)
        return profile

    def update(self, profile_id: str, **fields: Any) -> BrowserProfile | None:
        """Update mutable fields on a profile."""
        profile = self._profiles.get(profile_id)
        if profile is None:
            return None

        allowed = {"name", "start_url", "proxy", "os_type", "browser_type", "plugin", "notes", "fingerprint"}
        for key, value in fields.items():
            if key in allowed:
                setattr(profile, key, value)

        self._save()
        return profile

    def delete(self, profile_id: str) -> bool:
        """Delete a profile and its user data directory."""
        profile = self._profiles.pop(profile_id, None)
        if profile is None:
            return False

        data_dir = profile.user_data_dir
        if data_dir.exists():
            shutil.rmtree(data_dir, ignore_errors=True)

        self._save()
        logger.info("Deleted browser profile '%s' (id=%s)", profile.name, profile_id)
        return True

    def set_status(self, profile_id: str, status: str) -> None:
        """Update status (IDLE/RUNNING/ERROR)."""
        profile = self._profiles.get(profile_id)
        if profile:
            profile.status = status
            if status == "RUNNING":
                profile.touch()
            self._save()

    # ── Persistence ───────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            self._profiles = {}
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._profiles = {
                pid: BrowserProfile.from_dict(data) for pid, data in raw.items()
            }
        except Exception:
            logger.warning("Failed to load browser profiles from %s", self._path, exc_info=True)
            self._profiles = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {pid: p.to_dict() for pid, p in self._profiles.items()}
        # Remove user_data_dir from persisted data (it's derived)
        for d in data.values():
            d.pop("user_data_dir", None)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Singleton ─────────────────────────────────────────────────────

_store_instance: ProfileStore | None = None


def get_profile_store() -> ProfileStore:
    """Get the singleton profile store instance."""
    global _store_instance
    if _store_instance is None:
        _store_instance = ProfileStore()
    return _store_instance


__all__ = ["BrowserProfile", "ProfileStore", "get_profile_store"]
