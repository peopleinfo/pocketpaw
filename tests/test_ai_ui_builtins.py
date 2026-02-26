from pocketpaw.ai_ui.builtins import get_gallery


def test_templates_present_in_gallery():
    gallery = get_gallery()
    ids = {entry.get("id") for entry in gallery}
    assert "counter-template" in ids
    assert "g4f-chat-template" in ids
