"""xAI images via the official SDK. One paid call, no automatic resubmission."""
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
from uuid import uuid4

from filelock import FileLock
from PIL import Image

from app.config import config
from app.services import generation_progress
from app.utils.atomic_files import write_bytes_atomic

DEFAULT_MODEL = 'grok-imagine-image'


class GrokError(ValueError):
    pass


class GrokRefusal(GrokError):
    pass


def api_key(settings=None):
    settings = config.app if settings is None else settings
    return str(settings.get('grok_image_api_key') or os.environ.get('XAI_API_KEY') or '').strip()


def is_enabled(settings=None):
    return bool(api_key(settings))


def freeze(params, settings=None):
    settings = config.app if settings is None else settings
    if params.grok_model is None:
        params.grok_model = str(settings.get('grok_image_model') or DEFAULT_MODEL).strip()
    if not api_key(settings):
        raise GrokError('Configure a chave xAI/Grok em Configurar fontes de material')
    if not params.grok_model or len(params.grok_model) > 120:
        raise GrokError('Informe um modelo de imagens disponível na sua conta xAI')


def _client(key, timeout):
    try:
        from xai_sdk import Client
    except ImportError:
        raise GrokError('Execute PREPARAR_GROK_WINDOWS.bat para instalar o SDK oficial xAI') from None
    return Client(api_key=key, timeout=timeout,
                  channel_options=[('grpc.enable_retries', 0), ('grpc.service_config', '{}')])


def generate(params, prompt, directory, *, before_submit=None, settings=None, existing_only=False):
    settings = config.app if settings is None else settings
    freeze(params, settings)
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 10000:
        raise GrokError('O prompt Grok deve ter entre 1 e 10000 caracteres')
    try:
        timeout = float(settings.get('grok_image_timeout_seconds', 600))
    except (ValueError, TypeError):
        raise GrokError('Configure a espera Grok entre 30 e 1800 segundos') from None
    if not math.isfinite(timeout) or not 30 <= timeout <= 1800:
        raise GrokError('Configure a espera Grok entre 30 e 1800 segundos')
    spec = {'model': params.grok_model, 'prompt': prompt, 'image_format': 'base64',
            'aspect_ratio': getattr(params.video_aspect, 'value', params.video_aspect)}
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    ledger, image = folder/'grok-image.json', folder/'image.png'
    def save(state):
        write_bytes_atomic(ledger, json.dumps(state, ensure_ascii=False, indent=2).encode())
    with FileLock(str(ledger)+'.lock', timeout=0):
        if ledger.exists():
            state = json.loads(ledger.read_text(encoding='utf-8'))
            if state.get('version') != 1 or state.get('fingerprint') != fingerprint:
                raise GrokError('As configurações diferem da imagem Grok salva')
            if state.get('status') == 'refused':
                raise GrokRefusal('A xAI recusou a imagem por segurança; nenhum novo pedido foi feito')
            if image.is_file() and hashlib.sha256(image.read_bytes()).hexdigest() == state.get('sha256'):
                return image, {k: state[k] for k in ('request_id','model','cost_usd') if k in state}
            if not (folder/'response.b64').is_file():
                raise GrokError('Resultado Grok não confirmado. Consulte o painel xAI; não haverá novo envio automático')
        else:
            if existing_only:
                raise GrokError('Registro Grok ausente; geração paga não será reenviada')
            # Resolve SDK/credentials before marking an intent that might have cost.
            client = _client(api_key(settings), timeout)
            state = {'version': 1, 'provider': 'grok_image', 'request_id': str(uuid4()),
                     'model': params.grok_model, 'fingerprint': fingerprint, 'status': 'submission_unconfirmed'}
            try:
                save(state)
                if before_submit:
                    before_submit()
                generation_progress.submitting('grok_image')
                with client:
                    result = client.image.sample(**spec)
                    if not result.respect_moderation:
                        state['status'] = 'refused'
                        save(state)
                        raise GrokRefusal('A xAI recusou a imagem por segurança; nenhum novo pedido foi feito')
                    encoded = result.base64
                    if not isinstance(encoded, str) or len(encoded) > 36*1024*1024:
                        raise GrokError('Resposta de imagem Grok inválida ou muito grande')
                    write_bytes_atomic(folder/'response.b64', encoded.encode('ascii'))
                    cost = result.cost_usd
                    if isinstance(cost, (int,float)) and not isinstance(cost,bool) and math.isfinite(cost) and cost >= 0:
                        state['cost_usd'] = cost
                    state['status'] = 'received'
                    save(state)
            except GrokError:
                raise
            except Exception as exc:
                code = ''
                try:
                    candidate = exc.code().name
                    if candidate in {'UNAUTHENTICATED','PERMISSION_DENIED','RESOURCE_EXHAUSTED','DEADLINE_EXCEEDED','UNAVAILABLE','INVALID_ARGUMENT','INTERNAL'}:
                        code = ' (' + candidate + ')'
                except Exception:
                    pass
                raise GrokError('Falha na geração Grok' + code + '; pedido preservado para revisão, sem repetição automática') from None
            finally:
                client.close()
        try:
            content = base64.b64decode((folder/'response.b64').read_bytes(), validate=True)
            with Image.open(io.BytesIO(content)) as source:
                if source.width*source.height > 50_000_000:
                    raise ValueError()
                source.load()
                target = io.BytesIO()
                source.convert('RGB').save(target, format='PNG')
                content = target.getvalue()
        except Exception:
            raise GrokError('Resultado Grok salvo não é uma imagem válida; nenhuma nova geração foi solicitada') from None
        write_bytes_atomic(image, content)
        state.update(status='saved', sha256=hashlib.sha256(content).hexdigest())
        save(state)
        (folder/'response.b64').unlink(missing_ok=True)
        return image, {k: state[k] for k in ('request_id','model','cost_usd') if k in state}
