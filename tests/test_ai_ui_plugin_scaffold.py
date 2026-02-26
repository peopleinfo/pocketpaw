from pathlib import Path

from pocketpaw.ai_ui.plugin_scaffold import scaffold_plugin


def test_scaffold_python_repo_creates_manifest_and_scripts(tmp_path: Path):
    source = tmp_path / "sample-repo"
    source.mkdir()
    (source / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (source / "requirements.txt").write_text("fastapi\n")

    project_root = tmp_path / "workspace"
    result = scaffold_plugin(str(source), project_root=project_root, install=True)

    plugin_dir = project_root / "plugins" / result.plugin_id
    assert result.already_plugin is False
    assert plugin_dir.exists()
    assert (plugin_dir / "pocketpaw.json").exists()
    assert (plugin_dir / "install.sh").exists()
    assert (plugin_dir / "start.sh").exists()


def test_scaffold_keeps_existing_manifest(tmp_path: Path):
    source = tmp_path / "already-plugin"
    source.mkdir()
    (source / "pocketpaw.json").write_text('{"name":"Existing"}')
    (source / "main.py").write_text("print('ok')\n")

    project_root = tmp_path / "workspace"
    result = scaffold_plugin(str(source), project_root=project_root, install=True)

    plugin_dir = project_root / "plugins" / result.plugin_id
    assert result.already_plugin is True
    assert plugin_dir.exists()
    # Existing manifest should remain untouched.
    assert (plugin_dir / "pocketpaw.json").read_text() == '{"name":"Existing"}'
