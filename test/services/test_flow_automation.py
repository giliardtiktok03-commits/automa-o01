from types import SimpleNamespace
from unittest.mock import MagicMock
from PIL import Image
import pytest
from app.services import flow_automation as flow


class Node:
    def __init__(self, page, kind, text="", visible=True):
        self.page, self.kind, self.text, self.visible = page, kind, text, visible
        self.selected = False

    def count(self):
        return int(self.visible)

    def nth(self, _):
        return self

    def hover(self, **_):
        pass

    def is_visible(self):
        return self.visible

    def click(self, **_):
        self.page.actions.append(self.kind)
        self.selected = True
        if self.kind == "submit":
            self.page.submissions += 1

    def get_attribute(self, key):
        if key == "src":
            return "https://image.example.test/new.png"
        if key == "aria-pressed":
            return "true" if self.selected else "false"

    def inner_text(self, **_):
        return self.text

    def all_inner_texts(self):
        return []

    def evaluate(self, _):
        return True

    def fill(self, value, **_):
        self.page.prompt = value

    def locator(self, selector):
        if selector == "xpath=..":
            return Node(self.page, "parent")
        if "ancestor" in selector:
            return Node(self.page, "card")
        return Node(self.page, "download")


class Page:
    url = "https://flow.google.com/project/test"

    def __init__(self, credits=0, ratio=True):
        self.actions = []
        self.submissions = 0
        self.prompt = ""
        self.credits = credits
        self.ratio = ratio

    def wait_for_load_state(self, *_, **__):
        pass

    def wait_for_timeout(self, *_):
        pass

    def get_by_role(self, role, name=None, **_):
        pattern = name.pattern if hasattr(name, "pattern") else name
        if "Imagem" in pattern:
            return Node(self, "image-mode")
        if "Nano Banana [0-9" in pattern:
            return Node(self, "model", flow.MODEL)
        return Node(self, "settings", "Nano Banana 2.1 x1")

    def get_by_text(self, text, **_):
        return Node(self, text, text, visible=self.ratio if text == "16:9" else True)

    def locator(self, selector):
        if selector == "body":
            return Node(self, "body", f"A geração vai usar {self.credits} créditos")
        if selector == "img":
            return Node(self, "result", visible=self.submissions > 0)
        if selector == '[role="alert"]':
            return Node(self, "alerts", visible=False)
        if "iframe" in selector:
            return Node(self, "captcha", visible=False)
        if "textarea" in selector:
            return Node(self, "editor")
        return Node(self, "submit")

    def expect_download(self, **_):
        event = MagicMock()

        def save(file):
            Image.new("RGB", (64, 64), "blue").save(file, format="PNG")

        event.__enter__.return_value = SimpleNamespace(
            value=SimpleNamespace(save_as=save)
        )
        return event


def test_configures_and_submits_once_then_downloads_only_new_result(tmp_path):
    page = Page()
    target = tmp_path / "result.png"
    flow.generate(page, "Historical scene", target, timeout=1)
    assert page.actions[:4] == ["image-mode", "settings", "16:9", "x1"]
    assert page.prompt == "Historical scene" and page.submissions == 1
    assert page.actions[-1] == "download"
    with Image.open(target) as image:
        assert image.size == (64, 64)


@pytest.mark.parametrize("page", [Page(credits=2), Page(ratio=False)])
def test_unconfirmed_controls_or_nonzero_cost_never_submit(page, tmp_path):
    with pytest.raises(flow.FlowError):
        flow.generate(page, "scene", tmp_path / "result.png", timeout=1)
    assert page.submissions == 0
    assert not (tmp_path / "result.png").exists()


def test_logged_out_browser_stops_without_submitting(tmp_path):
    page = Page()
    page.url = "https://accounts.google.com/signin"
    with pytest.raises(flow.FlowError, match="login"):
        flow.generate(page, "scene", tmp_path / "result.png")
    assert page.submissions == 0
