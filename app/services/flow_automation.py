"""Visible-UI Flow automation. No private endpoints, retries or bypasses."""
import re
import time
from urllib.parse import urlparse

from app.services.flow_browser import FlowError, FlowRefusal, _save_image

MODEL = 'Nano Banana 2.1'


def _one_visible(locator, label):
    matches = [locator.nth(i) for i in range(locator.count()) if locator.nth(i).is_visible()]
    if not matches:
        try:locator.first.wait_for(state='visible',timeout=5000)
        except Exception:pass
        matches = [locator.nth(i) for i in range(locator.count()) if locator.nth(i).is_visible()]
    if len(matches) != 1:
        raise FlowError(f'Flow control missing or ambiguous: {label}.')
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


def _selected(node):
    values=[node.get_attribute(k) for k in ('aria-pressed','aria-selected','aria-checked','data-state')]
    parent=node.locator('xpath=..')
    values += [parent.get_attribute(k) for k in ('aria-pressed','aria-selected','aria-checked','data-state')]
    return any(value in ('true','on','checked','active') for value in values)


def _choose(page, text):
    node = _one_visible(page.get_by_text(text, exact=True), text)
    if not _selected(node):node.click(timeout=5000)
    if not _selected(node):
        raise FlowError(f'Cannot confirm selected Flow option: {text}. No generation was submitted.')


def _image_mode(page):
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        for role in ('tab','button','radio'):
            nodes=page.get_by_role(role,name=re.compile(r'^(Imagem|Image)$',re.I))
            visible=[nodes.nth(i) for i in range(nodes.count()) if nodes.nth(i).is_visible()]
            if len(visible)==1:return visible[0]
        page.wait_for_timeout(100)
    raise FlowError('Não encontrei a opção Imagem no painel Flow; nenhum pedido foi enviado')


def _model_text(node):
    text=node.inner_text()
    text=re.sub(r'arrow_drop_down|expand_more|keyboard_arrow_down','',text)
    return ' '.join(text.replace('🍌','').split()).strip()


def _model_control(page):
    pattern=re.compile(r'Nano Banana|Imagen',re.I)
    for role in ('button','combobox'):
        nodes=page.get_by_role(role,name=pattern)
        matches=[]
        for i in range(nodes.count()):
            node=nodes.nth(i)
            if node.is_visible() and re.fullmatch(r'Nano Banana(?: [0-9.]+)?(?: Lite| Pro)?|Imagen [0-9.]+',_model_text(node),re.I):matches.append(node)
        if len(matches)==1:return matches[0]
    raise FlowError('Não encontrei o seletor único de modelo Flow; nenhum pedido foi enviado')


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


def generate(page, prompt, target, timeout=900, require_zero=True, *, aspect="16:9", model_name=MODEL, before_submit=None, on_stage=None):
    """One submit, only after all settings are verified; exact new result download."""
    def stage(value):
        if on_stage:on_stage(value)
    stage('aguardando_interface')
    page.wait_for_load_state('domcontentloaded', timeout=60000)
    page.locator('textarea, [contenteditable="true"]').first.wait_for(state='visible',timeout=30000)
    _blocked(page)
    stage('abrindo_configuracoes')
    settings = _button(page, r'Nano Banana|Imagen', 'image settings')
    settings.click(timeout=5000)
    stage('selecionando_imagem')
    mode = _image_mode(page)
    if not _selected(mode):mode.click(timeout=5000)
    if not _selected(mode):
        raise FlowError('Cannot confirm Flow image mode; no generation submitted')
    stage('selecionando_proporcao_quantidade')
    _choose(page, aspect)
    _choose(page, 'x1')
    stage('selecionando_modelo')
    model = _model_control(page)
    if _model_text(model) != model_name:
        model.click(timeout=5000)
        _one_visible(page.get_by_role('option', name=model_name, exact=True), model_name).click(timeout=5000)
    if model_name != _model_text(model):
        raise FlowError('Flow model could not be confirmed; no generation submitted')
    stage('confirmando_custo')
    if require_zero:
        text = page.locator('body').inner_text()
        if not re.search(r'(vai usar|will use|costs?)\s*0\s*(créditos|credits)', text, re.I):
            raise FlowError('Flow did not confirm zero credits. No generation submitted.')
    # Close settings via its own trigger; no keyboard shortcuts that might submit.
    settings.click(timeout=5000)
    stage('preenchendo_prompt')
    editor = _one_visible(page.locator('textarea, [contenteditable="true"]'), 'prompt editor')
    editor.fill(prompt, timeout=5000)
    before = set(_images(page))
    previous_alerts = set(page.locator('[role="alert"]').all_inner_texts())
    submit = _one_visible(page.locator('button[aria-label="Send prompt"], button[aria-label="Generate"], '
                         'button[aria-label="Gerar"], button[aria-label="Enviar"], button:has-text("arrow_forward")'), 'submit')
    stage('enviando_prompt')
    if before_submit:
        before_submit()
    submit.click(timeout=5000)  # Never retried, even if result becomes unknown.
    stage('aguardando_imagem')
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
            stage('baixando_imagem')
            with page.expect_download(timeout=60000) as event:
                download.click(timeout=5000)
            _save_image(event.value, target)
            return
        page.wait_for_timeout(500)
    raise FlowError('Flow generation result timed out. Review project before another request.')
