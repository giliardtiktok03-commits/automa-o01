"""DeepInfra image/thumbnail controls. No generation during UI rendering."""
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
    st.markdown('**DeepInfra — Modelos de imagens**')
    key = st.text_input('Chave da API DeepInfra', value=deepinfra.api_key(settings), type='password',
                        key='deepinfra_image_api_key_input', on_change=save, args=('deepinfra_api_key','deepinfra_image_api_key_input')).strip()
    set_config('app','deepinfra_api_key',key)
    st.caption('Também aceita DEEPINFRA_API_KEY e DEEPINFRA_IMAGE_MODEL. Variáveis de ambiente prevalecem nas novas gerações. A chave não entra em logs ou relatórios. A geração usa saldo DeepInfra.')
    try:
        current = deepinfra.model(settings)
    except deepinfra.DeepInfraError as exc:
        st.error(str(exc))
        return
    selected = st.selectbox('Modelo de imagens DeepInfra', list(deepinfra.MODELS), index=list(deepinfra.MODELS).index(current), format_func=deepinfra.MODELS.get, key='deepinfra_image_model_input')
    set_config('app','deepinfra_image_model',selected)
    effective = deepinfra.model({**settings, 'deepinfra_image_model':selected})
    st.caption('Modelo efetivo: '+effective)
    steps = st.number_input('Passos SDXL Turbo', min_value=1, max_value=4, value=int(settings.get('deepinfra_steps',1)), key='deepinfra_steps_input', disabled=effective != deepinfra.MODEL)
    set_config('app','deepinfra_steps',steps)
    timeout = st.number_input('Espera máxima por imagem DeepInfra (segundos)', min_value=30, max_value=1800, value=int(settings.get('deepinfra_timeout_seconds',180)), step=30, key='deepinfra_timeout_input')
    set_config('app','deepinfra_timeout_seconds',timeout)
    active = {**settings,'deepinfra_api_key':key,'deepinfra_image_model':selected,'deepinfra_timeout_seconds':timeout,'deepinfra_steps':steps}
    st.caption('Uma imagem por solicitação. FLUX e PrunaAI P-Image usam a API OpenAI-compatible da DeepInfra; SDXL conserva a API anterior. Resposta Base64 ou URL é validada e salva como PNG. O vídeo usa seu ajuste de quadro; thumbnails usam recorte central em 1280×720, sem esticar.')
    prompt = st.text_area('Prompt do teste DeepInfra', value='Realistic documentary illustration of a submarine at sea, wide composition, no text.',key='deepinfra_test_prompt')
    job = st.session_state.get('deepinfra_test_job')
    start = st.button('Testar DeepInfra', disabled=not key or bool(job),key='deepinfra_test_start')
    resume = st.button('Recuperar resultado salvo do mesmo teste', disabled=not key or not job,key='deepinfra_test_resume')
    if job and st.button('Preparar novo teste (não envia imagem)',key='deepinfra_test_reset'):
        st.session_state.pop('deepinfra_test_job',None)
        st.rerun()
    if start:
        job = {'params':VideoParams(video_subject='Teste DeepInfra',video_aspect='16:9',deepinfra_steps=steps,deepinfra_model=effective).model_dump(mode='json'), 'prompt':prompt,'directory':str(Path(utils.storage_dir())/'deepinfra-tests'/str(uuid4()))}
        st.session_state.deepinfra_test_job = job
    if start or resume:
        begin=time.monotonic()
        try:
            with st.spinner('Gerando uma única imagem DeepInfra…'):
                image, details=deepinfra.generate(VideoParams.model_validate(job['params']),job['prompt'],job['directory'],settings=active,existing_only=bool(resume))
            st.session_state.deepinfra_test_result={'image':str(image),'details':details,'seconds':round(time.monotonic()-begin,1)}
            st.session_state.pop('deepinfra_test_job',None)
        except deepinfra.DeepInfraError as exc:
            st.warning(str(exc))
    result=st.session_state.get('deepinfra_test_result')
    if result:
        st.image(result['image'])
        st.caption(f"Tempo: {result['seconds']} s")
        st.json(result['details'])
        path=Path(result['image'])
        if path.is_file():st.download_button('Baixar imagem de teste',path.read_bytes(),'deepinfra-test.png','image/png',key='deepinfra_test_download')
    enabled=st.checkbox('Ativar geração de thumbnails DeepInfra',value=bool(settings.get('deepinfra_thumbnails_enabled',False)),key='deepinfra_thumbnails_enabled')
    set_config('app','deepinfra_thumbnails_enabled',enabled)
    if enabled:
        st.markdown('**Thumbnail · DeepInfra**')
        thumb_prompt=st.text_area('Prompt da thumbnail',value='Documentary thumbnail background: a submarine beneath dramatic storm clouds, wide shot, no text.',key='deepinfra_thumbnail_prompt')
        thumb_job=st.session_state.get('deepinfra_thumbnail_job')
        create=st.button('Gerar 1 thumbnail DeepInfra',key='deepinfra_thumbnail_generate',disabled=not key or bool(thumb_job))
        recover=st.button('Recuperar thumbnail salva',key='deepinfra_thumbnail_recover',disabled=not key or not thumb_job)
        if thumb_job and st.button('Preparar nova thumbnail (não envia imagem)',key='deepinfra_thumbnail_reset'):
            st.session_state.pop('deepinfra_thumbnail_job',None)
            st.rerun()
        if create:
            thumb_job={'prompt':thumb_prompt,'directory':str(Path(utils.storage_dir())/'thumbnails'/str(uuid4())), 'model':effective,'steps':steps}
            st.session_state.deepinfra_thumbnail_job=thumb_job
        if create or recover:
            try:
                with st.spinner('Gerando thumbnail…'):
                    # Frozen per-job model remains independent of later UI edits.
                    thumb_settings={**active,'deepinfra_thumbnails_enabled':True,'deepinfra_image_model':thumb_job['model'],'deepinfra_steps':thumb_job.get('steps',steps)}
                    image, details=deepinfra.generate_thumbnail(thumb_job['prompt'],thumb_job['directory'],settings=thumb_settings,existing_only=bool(recover),model_id=thumb_job['model'])
                st.session_state.deepinfra_thumbnail_result={'image':str(image),'details':details}
                st.session_state.pop('deepinfra_thumbnail_job',None)
            except deepinfra.DeepInfraError as exc:st.warning(str(exc))
        thumbnail=st.session_state.get('deepinfra_thumbnail_result')
        if thumbnail:
            st.image(thumbnail['image'])
            path=Path(thumbnail['image'])
            if path.is_file():st.download_button('Baixar thumbnail 1280×720',path.read_bytes(),'thumbnail.png','image/png',key='deepinfra_thumbnail_download')
