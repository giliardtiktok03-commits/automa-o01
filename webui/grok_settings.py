"""Grok image settings, separate from the central OpenAI configuration."""
import time
from pathlib import Path
from uuid import uuid4

import streamlit as st
from app.models.schema import VideoParams
from app.services import grok_image as grok
from app.utils import utils


def render(settings, set_config):
    def save(name, widget):
        set_config('app', name, st.session_state[widget])
    st.markdown('**Grok · Imagens IA pela xAI**')
    key = st.text_input('Chave da API xAI/Grok', value=grok.api_key(settings), type='password',
                        key='grok_image_api_key_input', on_change=save, args=('grok_image_api_key','grok_image_api_key_input')).strip()
    set_config('app','grok_image_api_key',key)
    st.caption('Obtenha sua chave em https://console.x.ai/. A API pode consumir saldo próprio, separado da assinatura do aplicativo Grok. A chave fica apenas na configuração local.')
    model = st.text_input('Modelo de imagem Grok', value=str(settings.get('grok_image_model') or grok.DEFAULT_MODEL),
                          key='grok_model_input', on_change=save, args=('grok_image_model','grok_model_input')).strip()
    set_config('app','grok_image_model',model)
    timeout = st.number_input('Espera máxima por imagem Grok (segundos)', min_value=30, max_value=1800,
                              value=int(settings.get('grok_image_timeout_seconds',600)), step=30,
                              key='grok_timeout_input', on_change=save, args=('grok_image_timeout_seconds','grok_timeout_input'))
    set_config('app','grok_image_timeout_seconds',timeout)
    st.caption('Usa o SDK oficial xAI. Execute PREPARAR_GROK_WINDOWS.bat uma vez após atualizar. Uma imagem por pedido, respeitando a proporção do vídeo e o limite global de imagens. Sem fallback OpenAI ou Runware. Custo disponível após a resposta; não há teto financeiro prévio nesta integração.')
    prompt = st.text_area('Prompt do teste Grok', value='Historical documentary illustration of a nineteenth-century steam locomotive. No text.', key='grok_test_prompt')
    job = st.session_state.get('grok_test_job')
    start = st.button('Gerar 1 imagem de teste Grok (cobrado)', disabled=not key or bool(job), key='grok_test_start')
    resume = st.button('Recuperar resultado salvo do mesmo teste', disabled=not key or not job, key='grok_test_resume')
    if start:
        job = {'params': VideoParams(video_subject='Teste Grok',video_aspect='16:9',grok_model=model).model_dump(mode='json'),
               'prompt':prompt,'directory':str(Path(utils.storage_dir())/'grok-tests'/str(uuid4()))}
        st.session_state.grok_test_job = job
    if start or resume:
        begin=time.monotonic()
        try:
            with st.spinner('Gerando uma imagem pelo Grok…'):
                image, details = grok.generate(VideoParams.model_validate(job['params']),job['prompt'],job['directory'],
                                               settings={**settings,'grok_image_api_key':key,'grok_image_timeout_seconds':timeout},existing_only=bool(resume))
            st.session_state.grok_test_result={'image':str(image),'details':details,'seconds':round(time.monotonic()-begin,1)}
            st.session_state.pop('grok_test_job',None)
        except grok.GrokError as exc:
            st.warning(str(exc))
            if not (Path(job['directory'])/'grok-image.json').exists():
                st.session_state.pop('grok_test_job',None)
    if job:
        st.caption('Pasta do teste: '+job['directory'])
    result=st.session_state.get('grok_test_result')
    if result:
        st.image(result['image'])
        st.write(f"Tempo desta execução: {result['seconds']} s")
        st.json(result['details'])
