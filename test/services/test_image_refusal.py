import pytest
from app.services import material


@pytest.mark.parametrize("detail,refused", [
    ("HTTP 400: Your request was rejected by the safety system. safety_violations=[violence]", True),
    ("HTTP 400: content_policy_violation", True),
    ("HTTP 401: invalid key", False),
    ("HTTP 400: invalid model", False),
    ("HTTP 503: unavailable", False),
])
def test_explicit_refusals_are_distinguished_from_technical_failures(monkeypatch, detail, refused):
    monkeypatch.setattr(material, "_openai_image_endpoint", lambda: ("https://example.test/images", "test"))
    monkeypatch.setattr(material, "_openai_image_size", lambda *_: "1024x1024")
    monkeypatch.setattr(material, "_openai_image_prompt", lambda value: value)
    calls = []
    def request(*args):
        calls.append(args)
        return None, detail
    monkeypatch.setattr(material, "_request_openai_image", request)
    if refused:
        with pytest.raises(material.OpenAIImageRefusalError):
            material.generate_images_openai("context", 1, raise_on_refusal=True)
    else:
        assert material.generate_images_openai("context", 1, raise_on_refusal=True) == []
    assert len(calls) == 1
