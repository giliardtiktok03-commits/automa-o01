"""DeepInfra image settings, separate from the central OpenAI configuration."""
import time
from pathlib import Path
from uuid import uuid4

import streamlit as st
from app.models.schema import VideoParams
from app.services import deepinfra_image as deepinfra
from app.utils import utils


def render(settings, set_config):
    def save(name, widget):
        set_config('app', name, st.session_state[widget])
    st.markdown('**DeepInfra · SDXL Turbo**')
    key = st.text_input('Chave da API DeepInfra', value=deepinfra.api_key(settings), type='password',
                        key='deepinfra_image_api_key_input', on_change=save, args=('deepinfra_api_key','deepinfra_image_api_key_input')).strip()
    set_config('app','deepinfra_api_key',key)
    st.caption('Obtenha sua chave em https://deepinfra.com/dash/api_keys. Os pedidos podem consumir saldo da sua conta DeepInfra. A chave fica apenas na configuração local.')
    st.code(deepinfra.MODEL)
    steps = st.number_input('Passos SDXL Turbo', min_value=1, max_value=4,
                           value=int(settings.get('deepinfra_steps',1)), key='deepinfra_steps_input')
    set_config('app','deepinfra_steps',steps)
    timeout = st.number_input('Espera máxima por imagem DeepInfra (segundos)', min_value=30, max_value=1800,
                              value=int(settings.get('deepinfra_timeout_seconds',180)), step=30,
                              key='deepinfra_timeout_input', on_change=save, args=('deepinfra_timeout_seconds','deepinfra_timeout_input'))
    set_config('app','deepinfra_timeout_seconds',timeout)
    st.caption('Uma imagem por pedido. Horizontal: 1024×576; vertical: 576×1024; quadrada: 512×512. O Turbo usa poucos passos e pode ter menos detalhes que modelos maiores. Chamadas podem ser cobradas; confirme preço, disponibilidade e licença do modelo na DeepInfra. Sem repetição automática nem troca de provedor em falhas.')
    prompt = st.text_area('Prompt do teste DeepInfra', value='Historical documentary illustration of a nineteenth-century steam locomotive. No text.', key='deepinfra_test_prompt')
    job = st.session_state.get('deepinfra_test_job')
    start = st.button('Gerar 1 imagem de teste DeepInfra (cobrado)', disabled=not key or bool(job), key='deepinfra_test_start')
    resume = st.button('Recuperar resultado salvo do mesmo teste', disabled=not key or not job, key='deepinfra_test_resume')
    if start:
        job = {'params': VideoParams(video_subject='Teste DeepInfra',video_aspect='16:9',deepinfra_steps=steps).model_dump(mode='json'),
               'prompt':prompt,'directory':str(Path(utils.storage_dir())/'deepinfra-tests'/str(uuid4()))}
        st.session_state.deepinfra_test_job = job
    if start or resume:
        begin=time.monotonic()
        try:
            with st.spinner('Gerando uma imagem pelo DeepInfra…'):
                image, details = deepinfra.generate(VideoParams.model_validate(job['params']),job['prompt'],job['directory'],
                                               settings={**settings,'deepinfra_api_key':key,'deepinfra_timeout_seconds':timeout},existing_only=bool(resume))
            st.session_state.deepinfra_test_result={'image':str(image),'details':details,'seconds':round(time.monotonic()-begin,1)}
            st.session_state.pop('deepinfra_test_job',None)
        except deepinfra.DeepInfraError as exc:
            st.warning(str(exc))
            if not (Path(job['directory'])/'deepinfra-image.json').exists():
                st.session_state.pop('deepinfra_test_job',None)
    if job:
        st.caption('Pasta do teste: '+job['directory'])
    result=st.session_state.get('deepinfra_test_result')
    if result:
        st.image(result['image'])
        st.write(f"Tempo desta execução: {result['seconds']} s")
        st.json(result['details'])
