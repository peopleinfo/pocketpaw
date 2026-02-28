from unittest.mock import patch

from pocketpaw.ai_ui.builtins import get_gallery, get_install_block_reason, get_registry


def test_templates_present_in_gallery():
    gallery = get_gallery()
    ids = {entry.get("id") for entry in gallery}
    assert "counter-template" in ids
    assert "g4f-chat-template" in ids
    assert "wan2gp" in ids


def test_wan2gp_start_auto_enables_mac_mode():
    registry = get_registry()
    wan = registry["wan2gp"]
    start_script = wan["files"]["pocketpaw_start.py"]
    assert "Detected macOS; enabling optional WAN2GP_ALLOW_MAC=1 automatically." in start_script
    assert "To try on macOS, set WAN2GP_ALLOW_MAC=1 and start again." not in start_script
    assert "requirements.macos.txt" in start_script
    assert "onnxruntime>=1.18.0" in start_script
    assert "Wan2GP macOS preflight failed." in start_script


def test_wan2gp_install_blocked_on_macos_arm64():
    with patch("pocketpaw.ai_ui.builtins.platform.system", return_value="Darwin"), patch(
        "pocketpaw.ai_ui.builtins.platform.machine", return_value="arm64"
    ):
        reason = get_install_block_reason("wan2gp")
    assert reason is not None
    assert "macOS arm64" in reason


def test_counter_template_not_blocked():
    with patch("pocketpaw.ai_ui.builtins.platform.system", return_value="Darwin"), patch(
        "pocketpaw.ai_ui.builtins.platform.machine", return_value="arm64"
    ):
        reason = get_install_block_reason("counter-template")
    assert reason is None
