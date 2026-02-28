import asyncio
import sys
import types

import pytest

from pocketpaw.ai_ui import requirements


class _FakeProc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self._stdout = stdout.encode("utf-8")
        self._stderr = stderr.encode("utf-8")

    async def communicate(self):
        return self._stdout, self._stderr


@pytest.mark.asyncio
async def test_install_ffmpeg_uses_uv_pip_when_available(monkeypatch):
    calls: list[tuple[str, ...]] = []

    async def _fake_exec(*cmd, **kwargs):
        calls.append(tuple(cmd))
        return _FakeProc(0, stdout="ok")

    fake_static = types.SimpleNamespace(
        run=types.SimpleNamespace(
            get_or_fetch_platform_executables_else_raise=lambda: ("/tmp/ffmpeg", "/tmp/ffprobe")
        )
    )

    monkeypatch.setattr(
        requirements,
        "_find_binary",
        lambda name: "/usr/bin/uv" if name == "uv" else None,
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setitem(sys.modules, "static_ffmpeg", fake_static)

    ffmpeg_path = await requirements._install_ffmpeg()

    assert ffmpeg_path == "/tmp/ffmpeg"
    assert calls
    assert calls[0][:5] == ("/usr/bin/uv", "pip", "install", "--python", sys.executable)
    assert calls[0][-1] == "static-ffmpeg"


@pytest.mark.asyncio
async def test_install_ffmpeg_bootstraps_pip_when_missing(monkeypatch):
    calls: list[tuple[str, ...]] = []
    procs = [
        _FakeProc(1, stderr="No module named pip"),
        _FakeProc(0, stdout="ensurepip ok"),
        _FakeProc(0, stdout="pip ok"),
    ]

    async def _fake_exec(*cmd, **kwargs):
        calls.append(tuple(cmd))
        return procs.pop(0)

    fake_static = types.SimpleNamespace(
        run=types.SimpleNamespace(
            get_or_fetch_platform_executables_else_raise=lambda: ("/tmp/ffmpeg", "/tmp/ffprobe")
        )
    )

    monkeypatch.setattr(requirements, "_find_binary", lambda name: None)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setitem(sys.modules, "static_ffmpeg", fake_static)

    ffmpeg_path = await requirements._install_ffmpeg()

    assert ffmpeg_path == "/tmp/ffmpeg"
    assert (sys.executable, "-m", "ensurepip", "--upgrade") in calls
    assert calls.count((sys.executable, "-m", "pip", "install", "static-ffmpeg")) == 2


@pytest.mark.asyncio
async def test_install_requirement_includes_underlying_error(monkeypatch):
    async def _boom():
        raise RuntimeError("No module named pip")

    monkeypatch.setitem(requirements._INSTALLERS, "ffmpeg", _boom)

    with pytest.raises(RuntimeError, match="No module named pip"):
        await requirements.install_requirement("ffmpeg")
