"""Visible-UI Flow automation. No private endpoints, retries or bypasses."""
import re
import time
from urllib.parse import urlparse

from app.services.flow_browser import FlowError, FlowRefusal, _save_image

MODEL = 'Nano Banana 2.1'


def _one_visible(locator, label):
    matches = [locator.nth(i) for i in range(locator.count()) if locator.nth(i).is_visible()]
    if len(matches) != 1:
        raise FlowError(f'Flow control missing or ambiguous: {label}. No generation was submitted.')
    return matches[0]


def _button(page, pattern, label):
    return _one_visible(page.get_by_role('button', name=re.compile(pattern, re.I)), label)


def _blocked(page, previous_alerts=None):
    if urlparse(page.url).hostname != 'flow.google.com':
        raise FlowError('Flow session needs manual login; no automatic login or account change')
    body = page.locator('body').inner_text(timeout=3000)
    if previous_alerts is not None:
        alerts = set(page.locator('[role="alert"]').all_inner_texts()) - previous_alerts
        if any(re.search(r'request was rejected by the safety|violates our policies|violates.*policy|não foi possível gerar.*segurança|pedido.*recusado.*segurança', text, re.I) for text in alerts):
            raise FlowRefusal('Flow explicitly refused the request; no resubmission')
    if re.search(r'verify you are human|confirme que você é humano|unusual traffic|unusual activity|atividade incomum|limite.*atingido|quota exceeded|insufficient credits|créditos insuficientes', body, re.I):
        raise FlowError('Flow quota or verification blocked generation; resolve manually, no retry')
    captcha = page.locator('iframe[src*="recaptcha"], iframe[src*="hcaptcha"]')
    if any(captcha.nth(i).is_visible() for i in range(captcha.count())):
        raise FlowError('Flow requires CAPTCHA; automation stopped')


def _choose(page, text):
    node = _one_visible(page.get_by_text(text, exact=True), text)
    node.click(timeout=5000)
    # Only documented public UI state counts as selection evidence.
    selected = [node.get_attribute(k) for k in ('aria-pressed','aria-selected','aria-checked','data-state')]
    parent = node.locator('xpath=..')
    selected += [parent.get_attribute(k) for k in ('aria-pressed','aria-selected','aria-checked','data-state')]
    if not any(v in ('true','on','checked','active') for v in selected):
        raise FlowError(f'Cannot confirm selected Flow option: {text}. No generation was submitted.')


def _images(page):
    result = {}
    images = page.locator('img')
    for i in range(images.count()):
        node = images.nth(i)
        if node.is_visible() and node.evaluate('(el) => el.complete && el.naturalWidth >= 128 && el.naturalHeight >= 128'):
            src = node.get_attribute('src')
            if src:
                result[src] = node
    return result


def generate(page, prompt, target, timeout=900, require_zero=True, *, aspect="16:9", model_name=MODEL, before_submit=None):
    """One submit, only after all settings are verified; exact new result download."""
    page.wait_for_load_state('domcontentloaded', timeout=60000)
    _blocked(page)
    mode = _button(page, r'^(Imagem|Image)$', 'image mode')
    mode.click(timeout=5000)
    if not any(mode.get_attribute(key) in ('true','on','checked','active') for key in ('aria-pressed','aria-selected','aria-checked','data-state')):
        raise FlowError('Cannot confirm Flow image mode; no generation submitted')
    settings = _button(page, r'Nano Banana|Imagen', 'image settings')
    settings.click(timeout=5000)
    _choose(page, aspect)
    _choose(page, 'x1')
    model = _one_visible(page.get_by_role('button', name=re.compile(r'^(Nano Banana [0-9.]+(?: Lite)?|Nano Banana Pro|Imagen [0-9.]+)$', re.I)), 'model selector')
    if model.inner_text().strip() != model_name:
        model.click(timeout=5000)
        _one_visible(page.get_by_role('option', name=model_name, exact=True), model_name).click(timeout=5000)
    if model_name != model.inner_text().strip():
        raise FlowError('Flow model could not be confirmed; no generation submitted')
    if require_zero:
        text = page.locator('body').inner_text()
        if not re.search(r'(vai usar|will use|costs?)\s*0\s*(créditos|credits)', text, re.I):
            raise FlowError('Flow did not confirm zero credits. No generation submitted.')
    # Close settings via its own trigger; no keyboard shortcuts that might submit.
    settings.click(timeout=5000)
    editor = _one_visible(page.locator('textarea, [contenteditable="true"]'), 'prompt editor')
    editor.fill(prompt, timeout=5000)
    before = set(_images(page))
    previous_alerts = set(page.locator('[role="alert"]').all_inner_texts())
    submit = _one_visible(page.locator('button[aria-label="Send prompt"], button[aria-label="Generate"], '
                         'button[aria-label="Gerar"], button[aria-label="Enviar"], button:has-text("arrow_forward")'), 'submit')
    if before_submit:
        before_submit()
    submit.click(timeout=5000)  # Never retried, even if result becomes unknown.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _blocked(page, previous_alerts)
        new = {src: node for src, node in _images(page).items() if src not in before}
        if len(new) > 1:
            raise FlowError('Multiple new Flow images; cannot correlate result safely. Review project, no retry.')
        if new:
            image = next(iter(new.values()))
            image.hover(timeout=5000)
            # Limit download lookup to the nearest result container, never a
            # page-wide button that could download old material.
            card = image.locator('xpath=ancestor::*[.//button[contains(@aria-label,"Download") or contains(@aria-label,"Baixar") or .//*[text()="download"]]][1]')
            if not card.count():
                page.wait_for_timeout(500)
                continue
            card = _one_visible(card, 'new image result card')
            download = _one_visible(card.locator('button[aria-label*="Download"], button[aria-label*="Baixar"], button:has-text("download")'), 'result download')
            with page.expect_download(timeout=60000) as event:
                download.click(timeout=5000)
            _save_image(event.value, target)
            return
        page.wait_for_timeout(500)
    raise FlowError('Flow generation result timed out. Review project before another request.')
