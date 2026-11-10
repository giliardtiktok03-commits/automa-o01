from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from PIL import Image
import pytest
from app.services import flow_automation as flow


class Node:
    def __init__(self, page, kind, text="", visible=True):
        self.page, self.kind, self.text, self.visible = page, kind, text, visible
        self.selected = False

    @property
    def first(self):return self

    def wait_for(self,**_):pass

    def count(self):
        return int(self.visible)

    def nth(self, _):
        return self

    def scroll_into_view_if_needed(self, **_):pass

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
        if pattern and 'Gatilho de configurações' in pattern:
            return Node(self,"settings","Nano Banana 2.1 x1")
        if role == "radio" and pattern and "16:9" in pattern:
            return Node(self,"16:9","16:9",visible=self.ratio)
        if role == "radio" and pattern and "x1" in pattern:
            return Node(self,"x1","x1")
        if pattern and "Imagem" in pattern:
            return Node(self, "image-mode")
        if pattern and "Nano Banana [0-9" in pattern:
            return Node(self, "model", flow.MODEL)
        if self.actions.count("settings") % 2:
            return Node(self,"model",flow.MODEL)
        return Node(self, "settings", "Nano Banana 2.1 x1")

    def get_by_text(self, text, **_):
        return Node(self, text, text, visible=self.ratio if text == "16:9" else True)

    def locator(self, selector):
        if "Gatilho de configurações" in selector:
            return Node(self,"settings","Nano Banana 2.1 x1")
        if selector == "body":
            return Node(self, "body", f"A geração vai usar {self.credits} créditos")
        if selector == "img" or selector.startswith("img[src="):
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
    assert page.actions[:4] == ["settings", "image-mode", "16:9", "x1"]
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


def test_real_chromium_visible_ui_single_submit_download(tmp_path):
    import base64,io,shutil
    from playwright.sync_api import sync_playwright
    chromium=shutil.which('chromium')
    if not chromium:pytest.skip('Local Chromium not installed')
    out=io.BytesIO()
    Image.new('RGB',(320,180),'blue').save(out,format='PNG')
    data='data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()
    html='''<html><body>
<button aria-label="Gatilho de configurações" onclick="let x=document.getElementById('settings');x.hidden=!x.hidden">Nano Banana 2.1 x1</button>
<button aria-label="Galeria Nano Banana 2.1">Red apple on background</button>
<div id="settings" hidden>
<button role="radio" aria-checked="true"><i>image</i> Imagem</button>
<button role="radio" aria-checked="false" onclick="this.setAttribute('aria-checked','true')"><i>crop_16_9</i> <div><span>16:9</span></div></button>
<button role="radio" aria-checked="false" onclick="let el=this;setTimeout(()=>el.setAttribute('aria-checked','true'),60)"><div><span>x1</span></div></button>
<button aria-label="Selecionar família de modelos">🍌 Nano Banana 2.1 keyboard_arrow_down</button><p>A geração vai usar 0 créditos</p></div>
<textarea></textarea>
<button aria-label="Iniciar geração" onclick="submitOne()">Enviar</button><div id="results"></div>
<script>
window.submissions=0;
function submitOne(){window.submissions++;let card=document.createElement('div');
let img=document.createElement('img');img.src=DATA;card.appendChild(img);
let button=document.createElement('button');button.setAttribute('aria-label','Download');button.textContent='Baixar';
button.onclick=()=>{let link=document.createElement('a');link.href=DATA;link.download='image.png';link.click()};
card.appendChild(button);document.getElementById('results').appendChild(card);}
</script></body></html>'''.replace('DATA',repr(data))
    with sync_playwright() as p:
        # Synthetic HTML only; no Google account or external website is accessed.
        browser=p.chromium.launch(executable_path=chromium,headless=True)
        try:
            page=browser.new_page(accept_downloads=True)
            page.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html; charset=utf-8',body=html))
            page.goto('https://flow.google.com/project/39a3cd68-17c5-4695-8c99-52ea21b38e66')
            before=Mock()
            target=tmp_path/'result.png'
            flow.generate(page,'Historical documentary test',target,timeout=10,before_submit=before)
            before.assert_called_once()
            assert page.evaluate('window.submissions')==1
            assert page.locator('textarea').input_value()=='Historical documentary test'
            with Image.open(target) as image:assert image.size==(320,180)
        finally:browser.close()


@pytest.mark.parametrize("sibling_title", [False, True, "deep", "zero-size-title", "flow-download-label"])
def test_recover_existing_card_menu_without_submitting(tmp_path, sibling_title):
    import base64, io, shutil
    from playwright.sync_api import sync_playwright
    chromium = shutil.which('chromium')
    if not chromium:
        pytest.skip('Local Chromium not installed')
    out = io.BytesIO()
    Image.new('RGB', (320, 180), 'green').save(out, format='PNG')
    data = 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()
    html = '''<html><body><textarea></textarea>
<button onclick="window.submissions++">Iniciar geração</button>
<div><button aria-label="Red apple on background"><img src="OLD"></button>
<button aria-label="Reutilizar comando"></button><button aria-label="Mais opções" onclick="throw Error('wrong card')"></button></div>
<div><button aria-label="Empty cafe on rainy morning"><img src="DATA"></button>
<button aria-label="Reutilizar comando"></button><button aria-label="Mais opções" onclick="document.getElementById('menu').hidden=false"></button></div>
<div role="menu" id="menu" hidden><button role="menuitem" onclick="downloadImage()">Baixar</button></div>
<script>window.submissions=0;function downloadImage(){let a=document.createElement('a');a.href='DATA';a.download='existing.png';a.click()}</script>
</body></html>'''.replace('DATA', data).replace('OLD', data+'#old')
    if sibling_title:
        html = html.replace('<button aria-label="Empty cafe on rainy morning"><img src="' + data + '"></button>', '<img src="' + data + '"><button><span>Empty cafe on rainy morning</span><i>edit</i></button>')
    if sibling_title == 'flow-download-label':
        html = html.replace('>Baixar</button>', '><span>download</span>\n<span>Fazer o download</span></button>')
    if sibling_title == 'zero-size-title':
        html = html.replace('<button><span>Empty cafe on rainy morning</span><i>edit</i></button>', '<button aria-label="Empty cafe on rainy morning" style="position:absolute;width:0;height:0;padding:0;border:0;overflow:hidden"></button>')
    if sibling_title == 'deep':
        html = html.replace('<span>Empty cafe on rainy morning</span>', '<div>' * 12 + '<span>Empty cafe on rainy morning</span>' + '</div>' * 12)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium, headless=True)
        try:
            page = browser.new_page(accept_downloads=True)
            page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html; charset=utf-8', body=html))
            page.goto('https://flow.google.com/project/39a3cd68-17c5-4695-8c99-52ea21b38e66')
            target = tmp_path / 'existing.png'
            flow.recover(page, 'Empty cafe on rainy morning', target)
            assert page.evaluate('window.submissions') == 0
            assert page.locator('textarea').input_value() == ''
            with pytest.raises(flow.FlowError, match='Não localizei'):
                flow._existing_image(page, 'Nonexistent title', timeout=0)
            page.evaluate("""() => {
                const card = document.createElement('div');
                const img = document.createElement('img');
                img.src = document.querySelector('img').src;
                const title = document.createElement('button');
                title.textContent = 'Empty cafe on rainy morning';
                card.append(img, title); document.body.append(card);
            }""")
            page.wait_for_function('Array.from(document.images).every(i => i.complete)')
            with pytest.raises(flow.FlowError, match='Mais de uma imagem'):
                flow._existing_image(page, 'Empty cafe on rainy morning', timeout=0)
            assert page.evaluate('window.submissions') == 0
            with Image.open(target) as image:
                assert image.size == (320, 180)
                assert image.getpixel((0, 0)) == (0, 128, 0)
        finally:
            browser.close()
