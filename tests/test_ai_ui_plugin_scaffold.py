import json
import subprocess
import sys
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
    assert (plugin_dir / "pocketpaw_install.py").exists()
    assert (plugin_dir / "pocketpaw_start.py").exists()
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


def test_scaffold_node_repo_creates_node_manifest(tmp_path: Path):
    source = tmp_path / "node-repo"
    source.mkdir()
    (source / "package.json").write_text(
        json.dumps({"name": "node-repo", "scripts": {"start": "node server.js --port 3100"}})
    )
    (source / "server.js").write_text("console.log('ok')\n")

    project_root = tmp_path / "workspace"
    result = scaffold_plugin(str(source), project_root=project_root, install=True)

    plugin_dir = project_root / "plugins" / result.plugin_id
    manifest = json.loads((plugin_dir / "pocketpaw.json").read_text(encoding="utf-8"))
    assert manifest["port"] == 3100
    assert "node" in manifest["requires"]
    assert manifest["start"] == "python pocketpaw_start.py"
    assert manifest["install"] == "python pocketpaw_install.py"


def test_scaffold_pinokio_repo_creates_clone_and_torch_config(tmp_path: Path):
    source = tmp_path / "pinokio-repo"
    source.mkdir()
    (source / "pinokio.js").write_text("module.exports = {title: 'Demo'}\n")
    (source / "torch.js").write_text("module.exports = {run: []}\n")
    (source / "install.js").write_text(
        """
module.exports = {
  run: [
    { when: "{{gpu === 'amd' || platform === 'darwin'}}", method: "notify" },
    { method: "shell.run", params: { message: ["git clone https://github.com/acme/demo app"] } }
  ]
}
"""
    )
    (source / "start.js").write_text(
        """
module.exports = {
  run: [
    { method: "shell.run", params: { message: ["python app.py --server-port 7007"] } }
  ]
}
"""
    )

    project_root = tmp_path / "workspace"
    result = scaffold_plugin(str(source), project_root=project_root, install=True)

    plugin_dir = project_root / "plugins" / result.plugin_id
    manifest = json.loads((plugin_dir / "pocketpaw.json").read_text(encoding="utf-8"))
    assert manifest["port"] == 7007
    assert manifest["env"]["PINOKIO_TORCH_ENABLE"] == "1"
    assert manifest["env"]["PINOKIO_SOURCE_REPO"] == "https://github.com/acme/demo"
    assert manifest["env"]["PINOKIO_ALLOW_NO_NVIDIA"] == "0"
    install_py = (plugin_dir / "pocketpaw_install.py").read_text(encoding="utf-8")
    assert "git clone" in install_py


def test_generated_pinokio_install_wrapper_runs_without_nameerror(tmp_path: Path):
    source = tmp_path / "pinokio-guarded"
    source.mkdir()
    (source / "pinokio.js").write_text("module.exports = {title: 'Demo'}\n")
    (source / "install.js").write_text(
        """
module.exports = {
  run: [
    { when: "{{gpu === 'amd' || platform === 'darwin'}}", method: "notify" }
  ]
}
"""
    )
    (source / "start.js").write_text(
        """
module.exports = {
  run: [
    { method: "shell.run", params: { message: ["python app.py --server-port 7007"] } }
  ]
}
"""
    )
    (source / "app.py").write_text("print('ok')\n")

    project_root = tmp_path / "workspace"
    result = scaffold_plugin(str(source), project_root=project_root, install=True)
    plugin_dir = project_root / "plugins" / result.plugin_id

    proc = subprocess.run(
        [sys.executable, "pocketpaw_install.py"],
        cwd=str(plugin_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    stderr = (proc.stderr or "").strip()
    assert "NameError" not in stderr
