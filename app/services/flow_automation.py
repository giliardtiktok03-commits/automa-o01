"""Visible-UI Flow automation. No private endpoints, retries or bypasses."""
import re
import json
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


def _settings_button(page):
    # Prefer the dedicated trigger. Gallery/media accessible names can also
    # contain Nano Banana; never combine them with the exact trigger selector.
    exact=page.locator('button[aria-label="Gatilho de configurações"], button[aria-label="Settings trigger"]')
    if any(exact.nth(i).is_visible() for i in range(exact.count())):
        return _one_visible(exact,'dedicated image settings trigger')
    trigger=page.get_by_role('button',name=re.compile(r'^(Gatilho de configurações|Settings trigger)$',re.I))
    if any(trigger.nth(i).is_visible() for i in range(trigger.count())):
        return _one_visible(trigger,'dedicated image settings trigger')
    return _button(page,r'Nano Banana|Imagen','image settings')


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
    radios=page.get_by_role('radio',name=re.compile(r'(?:^|\s)'+re.escape(text)+r'$',re.I))
    if any(radios.nth(i).is_visible() for i in range(radios.count())):
        node=_one_visible(radios,text)
    else:
        node = _one_visible(page.get_by_text(text, exact=True), text)
    if not _selected(node):node.click(timeout=5000)
    deadline=time.monotonic()+3
    while not _selected(node) and time.monotonic()<deadline:
        page.wait_for_timeout(100)
    if not _selected(node):
        raise FlowError(f'Cannot confirm selected Flow option: {text}. No generation was submitted.')


def _image_mode(page):
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        for role in ('tab','button','radio'):
            nodes=page.get_by_role(role,name=re.compile(r'^(?:image\s+)?(Imagem|Image)$',re.I))
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
        nodes=page.get_by_role(role)
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
                result[src] = page.locator("img[src="+json.dumps(src)+"]").first
    return result


def _visible(locator):
    return [locator.nth(i) for i in range(locator.count()) if locator.nth(i).is_visible()]


def _download_control(page, scope, target):
    pattern=re.compile(r'^(?:download\s+)?(?:Baixar|Download|Fazer download)(?: (?:imagem|image))?$',re.I)
    for role in ('menuitem','button','link'):
        nodes=_visible(scope.get_by_role(role,name=pattern))
        if len(nodes)==1:
            with page.expect_download(timeout=60000) as event:nodes[0].click(timeout=5000)
            _save_image(event.value,target)
            return True
    return False


def _download_result(page,image,target,on_stage=None):
    def stage(value):
        if on_stage:on_stage(value)
    stage('localizando_imagem_gerada')
    try:
        image.scroll_into_view_if_needed(timeout=3000)
        image.hover(timeout=2000)
    except Exception:
        pass  # Reacquire through its stable src locator; never resend the prompt.
    # Preserve direct-download cards, but do not accidentally use an old card's button.
    legacy=image.locator('xpath=ancestor::*[.//button[contains(@aria-label,"Download") or contains(@aria-label,"Baixar") or .//*[text()="download"]]][1]')
    if legacy.count() and legacy.locator('img').count()==1:
        card=_one_visible(legacy,'new image result card')
        download=_one_visible(card.locator('button[aria-label*="Download"], button[aria-label*="Baixar"], button:has-text("download")'),'result download')
        stage('baixando_imagem')
        with page.expect_download(timeout=60000) as event:download.click(timeout=5000)
        _save_image(event.value,target)
        return
    # Current Flow gallery puts Download in the new card's More options menu.
    scope=image
    for _ in range(24):
        scope=scope.locator('xpath=..')
        more=_visible(scope.get_by_role('button',name=re.compile(r'^(Mais opções|More options)$',re.I)))
        reuse=_visible(scope.get_by_role('button',name=re.compile(r'^(Reutilizar comando|Reuse prompt|Reuse command)$',re.I)))
        if len(more)==1 and len(reuse)==1:
            stage('abrindo_menu_da_imagem')
            more[0].click(timeout=5000)
            page.get_by_role('menu').first.wait_for(state='visible',timeout=5000)
            menus=_visible(page.get_by_role('menu'))
            if len(menus)!=1:raise FlowError('Menu de download ambíguo; imagem gerada preservada no Flow')
            stage('baixando_imagem')
            if _download_control(page,menus[0],target):return
            raise FlowError('Não encontrei download original no menu da imagem; nenhuma nova geração foi feita')
    raise FlowError('A imagem foi encontrada, mas seus controles de download não foram confirmados. Recupere a imagem existente, sem gerar outra.')


def _existing_image(page, title, timeout=30):
    # Flow can render the title and the image as siblings, and include icons in
    # the accessible button name. Match exact normalized labels/text instead.
    pattern = re.compile(r'^\s*' + r'\s+'.join(re.escape(word) for word in title.split()) + r'\s*$', re.I)
    deadline = time.monotonic() + timeout
    while True:
        candidates = []
        for locator in (page.get_by_role('button', name=pattern),
                        page.get_by_text(pattern, exact=True),
                        page.locator('button[aria-label=' + json.dumps(title) + ']')):
            for node in _visible(locator):
                scope = node
                for _ in range(24):
                    images = [image for image in _visible(scope.locator('img'))
                              if image.evaluate('(el) => el.complete && el.naturalWidth >= 128 && el.naturalHeight >= 128')]
                    if images:
                        # Never ascend through a container holding several assets.
                        if len(images) == 1:
                            candidates.append(images[0])
                        break
                    if scope.evaluate('(el) => el === document.body || el === document.documentElement'):
                        break
                    scope = scope.locator('xpath=..')
        unique = {}
        for image in candidates:
            src = image.get_attribute('src')
            if src:
                unique[src] = image
        if len(unique) == 1:
            return next(iter(unique.values()))
        if len(unique) > 1:
            raise FlowError('Mais de uma imagem corresponde ao título informado; confira o título no Flow. Nenhum novo pedido foi enviado.')
        if time.monotonic() >= deadline:
            raise FlowError('Não localizei um cartão com imagem única para esse título. Confira o título no projeto Flow; nenhum novo pedido foi enviado.')
        page.wait_for_timeout(250)


def recover(page,title,target,*,on_stage=None):
    title = str(title or '').strip()
    if not title or len(title)>200:raise FlowError('Informe o título exato da imagem já gerada')
    if on_stage:on_stage('localizando_imagem_existente')
    page.wait_for_load_state('domcontentloaded',timeout=60000)
    _blocked(page)
    image = _existing_image(page, title)
    _download_result(page,image,target,on_stage=on_stage)


def generate(page, prompt, target, timeout=900, require_zero=True, *, aspect="16:9", model_name=MODEL, before_submit=None, on_stage=None):
    """One submit, only after all settings are verified; exact new result download."""
    def stage(value):
        if on_stage:on_stage(value)
    stage('aguardando_interface')
    page.wait_for_load_state('domcontentloaded', timeout=60000)
    page.locator('textarea, [contenteditable="true"]').first.wait_for(state='visible',timeout=30000)
    _blocked(page)
    stage('abrindo_configuracoes')
    settings = _settings_button(page)
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
                         'button[aria-label="Gerar"], button[aria-label="Enviar"], button[aria-label="Iniciar geração"], '
                         'button[aria-label="Start generation"], button:has-text("arrow_forward")'), 'submit')
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
            _download_result(page,image,target,on_stage=on_stage)
            return
        page.wait_for_timeout(500)
    raise FlowError('Flow generation result timed out. Review project before another request.')
