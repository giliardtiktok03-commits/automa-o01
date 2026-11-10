"""DeepInfra SDXL Turbo inference; one submission, durable recovery, no retries."""
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
from PIL import Image

from app.config import config
from app.services import generation_progress
from app.utils.atomic_files import write_bytes_atomic

MODEL = 'stabilityai/sdxl-turbo'
ENDPOINT = 'https://api.deepinfra.com/v1/inference/' + MODEL
MAX_RESPONSE = 36 * 1024 * 1024


class DeepInfraError(ValueError):
    pass


class DeepInfraRefusal(DeepInfraError):
    pass


def api_key(settings=None):
    settings = config.app if settings is None else settings
    return str(settings.get('deepinfra_api_key') or os.environ.get('DEEPINFRA_API_KEY') or '').strip()


def freeze(params, settings=None):
    if not api_key(settings):
        raise DeepInfraError('Configure a chave DeepInfra em Configurar fontes de material → DeepInfra')
    if params.deepinfra_steps is None:
        params.deepinfra_steps = int((config.app if settings is None else settings).get('deepinfra_steps', 1))
    if not 1 <= params.deepinfra_steps <= 4:
        raise DeepInfraError('SDXL Turbo requer entre 1 e 4 passos')


def _post(payload, key, timeout):
    # No automatic HTTP retry or redirect carrying the API key.
    with requests.Session() as client:
        with client.post(ENDPOINT, headers={'Authorization': 'Bearer ' + key}, json=payload,
                         timeout=(15, timeout), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise DeepInfraError(f'DeepInfra HTTP {response.status_code}; sem reenvio automático')
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > MAX_RESPONSE:
                    raise DeepInfraError('Resposta DeepInfra excede o tamanho permitido')
                chunks.append(chunk)
            return b''.join(chunks)


def generate(params, prompt, directory, *, before_submit=None, settings=None, existing_only=False):
    settings = config.app if settings is None else settings
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
    spec = {'model': MODEL, **payload}
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    ledger, image, raw = folder/'deepinfra-image.json', folder/'image.png', folder/'response.json'
    def save(state):
        write_bytes_atomic(ledger, json.dumps(state, ensure_ascii=False, indent=2).encode())
    with FileLock(str(ledger)+'.lock', timeout=0):
        if ledger.exists():
            state = json.loads(ledger.read_text(encoding='utf-8'))
            if state.get('fingerprint') != fingerprint or state.get('version') != 1:
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
            state = dict(version=1, provider='deepinfra_image', fingerprint=fingerprint,
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
            except DeepInfraError:
                raise
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
                source.convert('RGB').save(out, format='PNG')
            details = {'model': MODEL, 'width': source.width, 'height': source.height,
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
