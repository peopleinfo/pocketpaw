"""Tests for Pinokio-style plugin isolation.

Verifies:
  - Manifest python_version / cuda_version fields are parsed and exposed
  - _ensure_isolated_python provisions an isolated Python via uv
  - _sandbox_env builds correct isolation (HOME, PATH, venv)
  - CUDA index URL mapping works correctly
  - list_plugins exposes python_version and cuda_version
  - wan2gp manifest declares correct isolation settings
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ─── CUDA index map tests ────────────────────────────────────────────────


class TestCudaIndexMap:
    """Test the CUDA version → PyTorch wheel index mapping."""

    def test_cuda_128_maps_correctly(self):
        from pocketpaw.ai_ui.plugins import get_cuda_index_url

        url = get_cuda_index_url("12.8")
        assert url == "https://download.pytorch.org/whl/cu128"

    def test_cuda_121_maps_correctly(self):
        from pocketpaw.ai_ui.plugins import get_cuda_index_url

        url = get_cuda_index_url("12.1")
        assert url == "https://download.pytorch.org/whl/cu121"

    def test_cuda_118_maps_correctly(self):
        from pocketpaw.ai_ui.plugins import get_cuda_index_url

        url = get_cuda_index_url("11.8")
        assert url == "https://download.pytorch.org/whl/cu118"

    def test_cuda_124_maps_correctly(self):
        from pocketpaw.ai_ui.plugins import get_cuda_index_url

        url = get_cuda_index_url("12.4")
        assert url == "https://download.pytorch.org/whl/cu124"

    def test_cuda_none_returns_none(self):
        from pocketpaw.ai_ui.plugins import get_cuda_index_url

        assert get_cuda_index_url(None) is None

    def test_cuda_empty_returns_none(self):
        from pocketpaw.ai_ui.plugins import get_cuda_index_url

        assert get_cuda_index_url("") is None

    def test_cuda_unknown_version_returns_none(self):
        from pocketpaw.ai_ui.plugins import get_cuda_index_url

        assert get_cuda_index_url("99.9") is None


# ─── Manifest schema tests ──────────────────────────────────────────────


class TestManifestSchema:
    """Test that python_version and cuda_version are read from manifests."""

    def test_wan2gp_manifest_has_python_version(self):
        from pocketpaw.ai_ui.builtins.wan2gp import DEFINITION

        manifest = DEFINITION["manifest"]
        assert manifest.get("python_version") == "3.10"

    def test_wan2gp_manifest_has_cuda_version(self):
        from pocketpaw.ai_ui.builtins.wan2gp import DEFINITION

        manifest = DEFINITION["manifest"]
        assert manifest.get("cuda_version") == "12.8"

    def test_wan2gp_cuda_maps_to_cu128_index(self):
        from pocketpaw.ai_ui.builtins.wan2gp import DEFINITION
        from pocketpaw.ai_ui.plugins import get_cuda_index_url

        cuda_ver = DEFINITION["manifest"].get("cuda_version")
        url = get_cuda_index_url(cuda_ver)
        assert url == "https://download.pytorch.org/whl/cu128"

    def test_manifest_without_versions_is_backward_compat(self):
        """Plugins without python_version/cuda_version still work."""
        from pocketpaw.ai_ui.plugins import get_cuda_index_url

        manifest = {
            "name": "Test App",
            "start": "python app.py",
        }
        assert manifest.get("python_version") is None
        assert manifest.get("cuda_version") is None
        assert get_cuda_index_url(manifest.get("cuda_version")) is None


# ─── Sandbox env tests ───────────────────────────────────────────────────


class TestSandboxEnv:
    """Test that _sandbox_env builds correct isolation."""

    def test_sandbox_env_isolates_home(self):
        from pocketpaw.ai_ui.plugins import _sandbox_env

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "test-plugin"
            plugin_dir.mkdir()
            manifest = {"name": "Test"}
            env = _sandbox_env(plugin_dir, manifest)
            assert env["HOME"] == str(plugin_dir)

    def test_sandbox_env_isolates_tmpdir(self):
        from pocketpaw.ai_ui.plugins import _sandbox_env

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "test-plugin"
            plugin_dir.mkdir()
            manifest = {"name": "Test"}
            env = _sandbox_env(plugin_dir, manifest)
            assert env["TMPDIR"] == str(plugin_dir / ".tmp")
            assert env["TEMP"] == str(plugin_dir / ".tmp")

    def test_sandbox_env_isolates_cache(self):
        from pocketpaw.ai_ui.plugins import _sandbox_env

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "test-plugin"
            plugin_dir.mkdir()
            manifest = {"name": "Test"}
            env = _sandbox_env(plugin_dir, manifest)
            assert env["XDG_CACHE_HOME"] == str(plugin_dir / ".cache")

    def test_sandbox_env_has_virtual_env(self):
        from pocketpaw.ai_ui.plugins import _sandbox_env

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "test-plugin"
            plugin_dir.mkdir()
            manifest = {"name": "Test"}
            env = _sandbox_env(plugin_dir, manifest)
            assert env["VIRTUAL_ENV"] == str(plugin_dir / ".venv")

    def test_sandbox_env_no_host_env_leak(self):
        """Verify host env vars don't leak into plugin sandbox."""
        from pocketpaw.ai_ui.plugins import _sandbox_env

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "test-plugin"
            plugin_dir.mkdir()
            manifest = {"name": "Test"}
            env = _sandbox_env(plugin_dir, manifest)
            # Should NOT contain random host env vars
            assert "RANDOM_HOST_VAR" not in env

    def test_sandbox_env_manifest_env_overlay(self):
        """Manifest env values are overlaid on top of sandbox."""
        from pocketpaw.ai_ui.plugins import _sandbox_env

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "test-plugin"
            plugin_dir.mkdir()
            manifest = {"name": "Test", "env": {"MY_CUSTOM_VAR": "hello"}}
            env = _sandbox_env(plugin_dir, manifest)
            assert env["MY_CUSTOM_VAR"] == "hello"

    def test_sandbox_port_from_manifest(self):
        from pocketpaw.ai_ui.plugins import _sandbox_env

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "test-plugin"
            plugin_dir.mkdir()
            manifest = {"name": "Test", "port": 7860}
            env = _sandbox_env(plugin_dir, manifest)
            assert env["PORT"] == "7860"

    def test_two_plugins_have_independent_sandboxes(self):
        """Two different plugins get completely separate environments."""
        from pocketpaw.ai_ui.plugins import _sandbox_env

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_a = Path(tmpdir) / "plugin-a"
            plugin_b = Path(tmpdir) / "plugin-b"
            plugin_a.mkdir()
            plugin_b.mkdir()

            env_a = _sandbox_env(plugin_a, {"name": "A", "port": 7860})
            env_b = _sandbox_env(plugin_b, {"name": "B", "port": 7861})

            assert env_a["HOME"] != env_b["HOME"]
            assert env_a["TMPDIR"] != env_b["TMPDIR"]
            assert env_a["VIRTUAL_ENV"] != env_b["VIRTUAL_ENV"]
            assert env_a["PORT"] == "7860"
            assert env_b["PORT"] == "7861"

    @pytest.mark.skipif(os.name != "nt", reason="Windows-specific env behavior")
    def test_sandbox_env_windows_home_profile_vars(self):
        """Windows sandbox should expose home/profile vars so Path.home() works."""
        from pocketpaw.ai_ui.plugins import _sandbox_env

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "test-plugin"
            plugin_dir.mkdir()
            env = _sandbox_env(plugin_dir, {"name": "Test"})

            assert env["USERPROFILE"] == str(plugin_dir)
            assert env["APPDATA"] == str(plugin_dir / ".appdata")
            assert env["LOCALAPPDATA"] == str(plugin_dir / ".localappdata")
            assert env.get("HOMEDRIVE")
            assert env.get("HOMEPATH")

            probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; print(Path.home())",
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert probe.returncode == 0
            assert str(plugin_dir).lower() in probe.stdout.strip().lower()


# ─── Isolated Python provisioning tests ──────────────────────────────────


class TestIsolatedPython:
    """Test _ensure_isolated_python provisions isolated Python via uv."""

    def test_no_python_version_returns_none(self):
        from pocketpaw.ai_ui.plugins import _ensure_isolated_python

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "test-plugin"
            plugin_dir.mkdir()
            manifest = {"name": "Test"}
            result = _ensure_isolated_python(plugin_dir, manifest)
            assert result is None

    def test_empty_python_version_returns_none(self):
        from pocketpaw.ai_ui.plugins import _ensure_isolated_python

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "test-plugin"
            plugin_dir.mkdir()
            manifest = {"name": "Test", "python_version": ""}
            result = _ensure_isolated_python(plugin_dir, manifest)
            assert result is None

    @pytest.mark.skipif(
        not shutil.which("uv"),
        reason="uv not installed",
    )
    def test_provision_python_310_creates_venv(self):
        """Real test: provision Python 3.10 venv using uv."""
        from pocketpaw.ai_ui.plugins import _ensure_isolated_python

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "isolated-test"
            plugin_dir.mkdir()
            manifest = {"name": "Test", "python_version": "3.10"}

            result = _ensure_isolated_python(plugin_dir, manifest)

            assert result is not None, "Expected a venv python path"
            assert result.exists(), f"Venv python should exist at {result}"

            # Verify it's actually Python 3.10
            version_check = subprocess.run(
                [str(result), "-c",
                 "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                capture_output=True, text=True, timeout=10,
            )
            assert version_check.returncode == 0
            assert version_check.stdout.strip() == "3.10"

    @pytest.mark.skipif(
        not shutil.which("uv"),
        reason="uv not installed",
    )
    def test_provision_is_idempotent(self):
        """Calling _ensure_isolated_python twice doesn't break anything."""
        from pocketpaw.ai_ui.plugins import _ensure_isolated_python

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "idempotent-test"
            plugin_dir.mkdir()
            manifest = {"name": "Test", "python_version": "3.10"}

            result1 = _ensure_isolated_python(plugin_dir, manifest)
            result2 = _ensure_isolated_python(plugin_dir, manifest)

            assert result1 is not None
            assert result2 is not None
            assert str(result1) == str(result2)

    @pytest.mark.skipif(
        not shutil.which("uv"),
        reason="uv not installed",
    )
    def test_isolated_python_not_system_python(self):
        """Isolated Python should be different from system Python."""
        from pocketpaw.ai_ui.plugins import _ensure_isolated_python

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "not-system-test"
            plugin_dir.mkdir()
            manifest = {"name": "Test", "python_version": "3.10"}

            result = _ensure_isolated_python(plugin_dir, manifest)
            if result is None:
                pytest.skip("Could not provision Python 3.10")

            # The isolated python should be inside the plugin dir
            assert str(plugin_dir) in str(result)

            # It should NOT be the system python
            assert str(result) != sys.executable

    @pytest.mark.skipif(
        not shutil.which("uv"),
        reason="uv not installed",
    )
    def test_two_plugins_get_independent_pythons(self):
        """Each plugin gets its own independent Python installation."""
        from pocketpaw.ai_ui.plugins import _ensure_isolated_python

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_a = Path(tmpdir) / "plugin-a"
            plugin_b = Path(tmpdir) / "plugin-b"
            plugin_a.mkdir()
            plugin_b.mkdir()

            manifest = {"name": "Test", "python_version": "3.10"}

            py_a = _ensure_isolated_python(plugin_a, manifest)
            py_b = _ensure_isolated_python(plugin_b, manifest)

            assert py_a is not None
            assert py_b is not None
            assert str(py_a) != str(py_b)
            assert str(plugin_a) in str(py_a)
            assert str(plugin_b) in str(py_b)

    def test_no_uv_returns_none(self):
        """When uv is not available, returns None gracefully."""
        from pocketpaw.ai_ui.plugins import _ensure_isolated_python

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "no-uv-test"
            plugin_dir.mkdir()
            manifest = {"name": "Test", "python_version": "3.10"}

            with patch("shutil.which", return_value=None):
                result = _ensure_isolated_python(plugin_dir, manifest)
                assert result is None


# ─── list_plugins integration tests ──────────────────────────────────────


class TestListPluginsIsolation:
    """Test that list_plugins exposes python_version and cuda_version."""

    def test_plugin_with_versions_exposed(self):
        """A plugin with python_version/cuda_version in manifest shows them."""
        from pocketpaw.ai_ui.plugins import PLUGINS_DIR, list_plugins

        test_id = "_test_isolation_versions"
        test_dir = PLUGINS_DIR / test_id
        try:
            test_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "name": "Isolation Test",
                "python_version": "3.10",
                "cuda_version": "12.8",
                "port": 9999,
            }
            (test_dir / "pocketpaw.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            plugins = list_plugins()
            test_plugin = next((p for p in plugins if p["id"] == test_id), None)

            assert test_plugin is not None, f"Plugin {test_id} not found in list"
            assert test_plugin["python_version"] == "3.10"
            assert test_plugin["cuda_version"] == "12.8"
        finally:
            if test_dir.exists():
                shutil.rmtree(test_dir, ignore_errors=True)

    def test_plugin_without_versions_shows_none(self):
        """A plugin without python_version/cuda_version shows None."""
        from pocketpaw.ai_ui.plugins import PLUGINS_DIR, list_plugins

        test_id = "_test_isolation_no_versions"
        test_dir = PLUGINS_DIR / test_id
        try:
            test_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "name": "No Versions Test",
                "port": 9998,
            }
            (test_dir / "pocketpaw.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            plugins = list_plugins()
            test_plugin = next((p for p in plugins if p["id"] == test_id), None)

            assert test_plugin is not None
            assert test_plugin["python_version"] is None
            assert test_plugin["cuda_version"] is None
        finally:
            if test_dir.exists():
                shutil.rmtree(test_dir, ignore_errors=True)


# ─── Wan2GP builtin definition tests ─────────────────────────────────────


class TestWan2gpBuiltin:
    """Test the wan2gp builtin definition has correct isolation config."""

    def test_wan2gp_registered_in_builtins(self):
        from pocketpaw.ai_ui.builtins import get_registry

        registry = get_registry()
        assert "wan2gp" in registry

    def test_wan2gp_has_git_source(self):
        from pocketpaw.ai_ui.builtins import get_registry

        registry = get_registry()
        defn = registry["wan2gp"]
        assert defn["git_source"] == "https://github.com/deepbeepmeep/Wan2GP"

    def test_wan2gp_has_install_files(self):
        from pocketpaw.ai_ui.builtins import get_registry

        registry = get_registry()
        defn = registry["wan2gp"]
        assert "pocketpaw_install.py" in defn["files"]
        assert "pocketpaw_start.py" in defn["files"]

    def test_wan2gp_gallery_entry(self):
        from pocketpaw.ai_ui.builtins import get_gallery

        gallery = get_gallery()
        wan2gp_entries = [e for e in gallery if e.get("id") == "wan2gp"]
        assert len(wan2gp_entries) == 1
        assert wan2gp_entries[0]["source"] == "builtin:wan2gp"

    def test_wan2gp_manifest_port_7860(self):
        from pocketpaw.ai_ui.builtins import get_registry

        registry = get_registry()
        assert registry["wan2gp"]["manifest"]["port"] == 7860

    def test_wan2gp_requires_python_and_git(self):
        from pocketpaw.ai_ui.builtins import get_registry

        registry = get_registry()
        requires = registry["wan2gp"]["manifest"]["requires"]
        assert "python" in requires
        assert "git" in requires

    def test_wan2gp_full_isolation_config(self):
        """Wan2GP should declare full Pinokio-style isolation."""
        from pocketpaw.ai_ui.builtins import get_registry

        registry = get_registry()
        manifest = registry["wan2gp"]["manifest"]

        # Must have isolated Python 3.10
        assert manifest["python_version"] == "3.10", \
            "Wan2GP requires Python 3.10 for Sage/Flash prebuilt wheels"

        # Must have CUDA 12.8
        assert manifest["cuda_version"] == "12.8", \
            "Wan2GP uses cu128 PyTorch wheels"

        # Verify CUDA index URL resolves
        from pocketpaw.ai_ui.plugins import get_cuda_index_url
        assert get_cuda_index_url(manifest["cuda_version"]) == \
               "https://download.pytorch.org/whl/cu128"
