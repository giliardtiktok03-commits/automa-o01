"""DeepInfra image APIs: FLUX.1 Schnell, PrunaAI P-Image and legacy SDXL; no retries."""
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
from uuid import uuid4

import requests
from filelock import FileLock
from PIL import Image, ImageOps

from app.config import config
from app.services import generation_progress
from app.utils.atomic_files import write_bytes_atomic

MODEL = 'stabilityai/sdxl-turbo'
ENDPOINT = 'https://api.deepinfra.com/v1/inference/' + MODEL
FLUX_MODEL = 'black-forest-labs/FLUX-1-schnell'
P_IMAGE_MODEL = 'PrunaAI/p-image'
FLUX_ENDPOINT = 'https://api.deepinfra.com/v1/openai/images/generations'
MODELS = {FLUX_MODEL: 'DeepInfra — FLUX.1 Schnell', MODEL: 'DeepInfra — SDXL Turbo', P_IMAGE_MODEL: 'PrunaAI P-Image'}
MAX_RESPONSE = 36 * 1024 * 1024


class DeepInfraError(ValueError):
    pass


class DeepInfraRefusal(DeepInfraError):
    pass


def api_key(settings=None):
    settings = config.app if settings is None else settings
    return str(os.environ.get('DEEPINFRA_API_KEY') or settings.get('deepinfra_api_key') or '').strip()


def model(settings=None):
    settings = config.app if settings is None else settings
    selected = str(os.environ.get('DEEPINFRA_IMAGE_MODEL') or settings.get('deepinfra_image_model') or FLUX_MODEL).strip()
    if selected not in MODELS:
        raise DeepInfraError('Modelo DeepInfra não suportado: selecione FLUX.1 Schnell, SDXL Turbo ou PrunaAI P-Image')
    return selected


def freeze(params, settings=None):
    if not api_key(settings):
        raise DeepInfraError('Configure a chave DeepInfra em Configurar fontes de material → DeepInfra')
    if params.deepinfra_model is None:
        params.deepinfra_model = model(settings)
    if params.deepinfra_model not in MODELS:
        raise DeepInfraError("Modelo DeepInfra inválido")
    if params.deepinfra_steps is None:
        params.deepinfra_steps = int((config.app if settings is None else settings).get('deepinfra_steps', 1))
    if not 1 <= params.deepinfra_steps <= 4:
        raise DeepInfraError('SDXL Turbo requer entre 1 e 4 passos')


class DeepInfraHTTPError(DeepInfraError):
    def __init__(self, status, retry_after=None):
        self.status = status
        self.retry_after = retry_after
        reason = {401: 'autenticação inválida', 403: 'acesso recusado', 429: 'limite de requisições atingido'}.get(status, 'requisição não concluída')
        super().__init__(f'DeepInfra HTTP {status}: {reason}; sem reenvio automático')


def _rate_file(key):
    from app.utils import utils
    return Path(utils.storage_dir('deepinfra-limits', create=True)) / (hashlib.sha256(key.encode()).hexdigest() + '.json')


def _cooldown(key):
    import time
    path = _rate_file(key)
    if path.exists():
        try:
            remaining = float(json.loads(path.read_text()).get('until', 0)) - time.time()
        except (ValueError, TypeError):
            raise DeepInfraError('Registro de limite DeepInfra inválido; confira antes de reenviar') from None
        if remaining > 0:
            raise DeepInfraError(f'DeepInfra em espera por limite HTTP 429; tente após {math.ceil(remaining)} segundos')


def _retry_seconds(value):
    import time
    from email.utils import parsedate_to_datetime
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            seconds = 60
    return max(0, seconds) if math.isfinite(seconds) else 60


def _post(payload, key, timeout):
    # One request at a time per credential; shared 429 cooldown, no auto-retry.
    import time
    path = _rate_file(key)
    with FileLock(str(path) + '.lock', timeout=0):
        _cooldown(key)
        endpoint = FLUX_ENDPOINT if payload.get('model') in (FLUX_MODEL, P_IMAGE_MODEL) else ENDPOINT
        with requests.Session() as client:
            with client.post(endpoint, headers={'Authorization': 'Bearer ' + key}, json=payload,
                             timeout=(15, timeout), allow_redirects=False, stream=True) as response:
                if response.status_code != 200:
                    seconds = None
                    if response.status_code == 429:
                        seconds = _retry_seconds(response.headers.get('Retry-After'))
                        write_bytes_atomic(path, json.dumps({'until': time.time() + seconds}).encode())
                    raise DeepInfraHTTPError(response.status_code, seconds)
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_RESPONSE:
                        raise DeepInfraError('Resposta DeepInfra excede o tamanho permitido')
                    chunks.append(chunk)
                return b''.join(chunks)


def generate(params, prompt, directory, *, before_submit=None, settings=None, existing_only=False):
    settings = config.app if settings is None else settings
    # Old checkpoints did not contain model metadata and always used SDXL Turbo.
    previous_ledger = Path(directory) / 'deepinfra-image.json'
    if previous_ledger.is_file() and (existing_only or params.deepinfra_model is None):
        try:
            previous_state = json.loads(previous_ledger.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            raise DeepInfraError('Registro DeepInfra inválido; nenhuma geração solicitada') from None
        if previous_state.get('version') == 1 and not previous_state.get('model'):
            params.deepinfra_model = MODEL
        elif params.deepinfra_model is None:
            params.deepinfra_model = previous_state.get('model')
    freeze(params, settings)
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 10000:
        raise DeepInfraError('O prompt DeepInfra deve ter entre 1 e 10000 caracteres')
    try:
        timeout = float(settings.get('deepinfra_timeout_seconds', 180))
    except (TypeError, ValueError):
        raise DeepInfraError('Configure a espera DeepInfra entre 30 e 1800 segundos') from None
    if not math.isfinite(timeout) or not 30 <= timeout <= 1800:
        raise DeepInfraError('Configure a espera DeepInfra entre 30 e 1800 segundos')
    aspect = getattr(params.video_aspect, 'value', params.video_aspect)
    sizes = {'16:9': (1024, 576), '9:16': (576, 1024), '1:1': (512, 512)}
    if aspect not in sizes:
        raise DeepInfraError('Proporção não suportada pelo conector DeepInfra')
    width, height = sizes[aspect]
    payload = dict(prompt=prompt, num_images=1, width=width, height=height,
                   num_inference_steps=params.deepinfra_steps, guidance_scale=0)
    if params.deepinfra_model in (FLUX_MODEL, P_IMAGE_MODEL):
        payload = dict(model=params.deepinfra_model, prompt=prompt, n=1, size=f'{width}x{height}', response_format='b64_json')
    spec = {'model': params.deepinfra_model, **payload}
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    ledger, image, raw = folder/'deepinfra-image.json', folder/'image.png', folder/'response.json'
    def save(state):
        write_bytes_atomic(ledger, json.dumps(state, ensure_ascii=False, indent=2).encode())
    with FileLock(str(ledger)+'.lock', timeout=0):
        if ledger.exists():
            state = json.loads(ledger.read_text(encoding='utf-8'))
            if state.get('fingerprint') != fingerprint or state.get('version') not in (1, 2):
                raise DeepInfraError('As configurações diferem da imagem DeepInfra salva')
            if state.get('status') == 'refused':
                raise DeepInfraRefusal('DeepInfra sinalizou conteúdo recusado; nenhum novo pedido foi feito')
            if image.is_file() and hashlib.sha256(image.read_bytes()).hexdigest() == state.get('sha256'):
                return image, state.get('details', {})
            if not raw.is_file():
                raise DeepInfraError('Resultado DeepInfra não confirmado; confira o painel. Sem novo envio automático')
        else:
            if existing_only:
                raise DeepInfraError('Registro DeepInfra ausente; geração não será reenviada')
            _cooldown(api_key(settings))
            state = dict(version=2, model=params.deepinfra_model, provider='deepinfra_image', fingerprint=fingerprint,
                         status='submission_unconfirmed', request_id=str(uuid4()))
            save(state)
            if before_submit:
                before_submit()
            generation_progress.submitting('deepinfra_image')
            try:
                content = _post(payload, api_key(settings), timeout)
                write_bytes_atomic(raw, content)
                state['status'] = 'received'
                save(state)
            except DeepInfraHTTPError as exc:
                state.update(status='http_error', http_status=exc.status, retry_after_seconds=exc.retry_after)
                save(state)
                raise
            except DeepInfraError:
                raise
            except requests.Timeout:
                raise DeepInfraError('Espera DeepInfra excedida; confira o painel, sem reenvio automático') from None
            except Exception:
                raise DeepInfraError('Falha na chamada DeepInfra; resultado preservado para revisão, sem reenvio automático') from None
        try:
            if raw.stat().st_size > MAX_RESPONSE:
                raise ValueError()
            data = json.loads(raw.read_bytes())
            if any(data.get('nsfw_content_detected', [])):
                state['status'] = 'refused'
                save(state)
                raise DeepInfraRefusal('DeepInfra sinalizou conteúdo recusado; nenhum novo pedido foi feito')
            if params.deepinfra_model in (FLUX_MODEL, P_IMAGE_MODEL):
                if not isinstance(data.get('data'), list) or len(data['data']) != 1:
                    raise ValueError()
                item = data['data'][0]
                if not isinstance(item, dict):
                    raise ValueError()
                if item.get('b64_json'):
                    images = [item['b64_json']]
                elif item.get('url'):
                    from app.services.ai33.images import download_png
                    # Existing credential-free public HTTPS downloader; never forward Bearer.
                    images = [base64.b64encode(download_png(item['url'])).decode('ascii')]
                else:
                    raise ValueError()
            else:
                images = data['images']
            if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], str):
                raise ValueError()
            encoded = images[0]
            if encoded.startswith('data:'):
                header, separator, encoded = encoded.partition(',')
                if not separator or not header.startswith('data:image/') or not header.endswith(';base64'):
                    raise ValueError()
            decoded = base64.b64decode(''.join(encoded.split()), validate=True)
            with Image.open(io.BytesIO(decoded)) as source:
                if source.width * source.height > 20_000_000 or min(source.size) < 128:
                    raise ValueError()
                source.load()
                out = io.BytesIO()
                normalized = source.convert('RGB')
                if params.deepinfra_model in (FLUX_MODEL, P_IMAGE_MODEL):
                    normalized = ImageOps.fit(normalized, (width, height), method=Image.Resampling.LANCZOS)
                normalized.save(out, format='PNG')
            details = {'model': params.deepinfra_model, 'width': normalized.width, 'height': normalized.height,
                       'source_width': source.width, 'source_height': source.height,
                       'request_id': str(data.get('request_id') or state['request_id'])[:200]}
            cost = data.get('inference_status', {}).get('cost')
            if isinstance(cost, (float, int)) and not isinstance(cost, bool) and math.isfinite(cost) and cost >= 0:
                details['cost_usd'] = cost
        except DeepInfraRefusal:
            raise
        except Exception:
            raise DeepInfraError('Resposta DeepInfra salva inválida; nenhuma nova geração foi solicitada') from None
        write_bytes_atomic(image, out.getvalue())
        state.update(status='saved', sha256=hashlib.sha256(image.read_bytes()).hexdigest(), details=details)
        save(state)
        raw.unlink(missing_ok=True)
        return image, details


def fit_image(source, target, size):
    """Center crop to exact output dimensions, preserving aspect and removing metadata."""
    with Image.open(source) as image:
        image.load()
        fitted = ImageOps.fit(image.convert('RGB'), size, method=Image.Resampling.LANCZOS)
        out = io.BytesIO()
        fitted.save(out, format='PNG')
    write_bytes_atomic(target, out.getvalue())
    return Path(target)


def generate_thumbnail(prompt, directory, *, settings=None, existing_only=False, model_id=None):
    from app.models.schema import VideoParams
    settings = config.app if settings is None else settings
    if not settings.get('deepinfra_thumbnails_enabled', False):
        raise DeepInfraError('Ative a geração de thumbnails DeepInfra antes de gerar')
    params = VideoParams(video_subject='Thumbnail DeepInfra', video_aspect='16:9', deepinfra_model=model_id)
    image, details = generate(params, prompt, directory, settings=settings, existing_only=existing_only)
    thumbnail = fit_image(image, Path(directory) / 'thumbnail.png', (1280, 720))
    return thumbnail, {**details, 'output_width': 1280, 'output_height': 720}
