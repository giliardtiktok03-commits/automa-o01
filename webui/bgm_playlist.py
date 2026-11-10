"""Optional multi-file BGM controls; rendering never persists or encodes tracks."""
import hashlib
import streamlit as st
from app.services import bgm as bgm_service


def render(params, bgm_enabled):
    files = st.file_uploader('Adicionar músicas à playlist (até 200 MB por arquivo)', type=[ext.removeprefix('.') for ext in bgm_service.SUPPORTED_BGM_EXTENSIONS], accept_multiple_files=True, max_upload_size=bgm_service.MAX_BGM_UPLOAD_BYTES // (1024 * 1024), key='bgm_playlist_uploads')
    params.bgm_file = ''
    st.caption('Até 20 faixas. Tocam em sequência; ao terminar a playlist, ela repete até o vídeo acabar. O volume configurado acima vale para todas.')
    if len(files) > 20:
        st.error('Selecione no máximo 20 músicas.')
        st.session_state['bgm_playlist_missing'] = True
        return None
    if not files:
        st.session_state['bgm_playlist_missing'] = bgm_enabled
        return None
    signature = hashlib.sha256(repr([(item.name,item.size) for item in files]).encode()).hexdigest()[:12]
    order = st.multiselect('Ordem das músicas — remova e selecione novamente para mover ao final',list(range(len(files))),default=list(range(len(files))),format_func=lambda i:f'{i+1}. {files[i].name}',key='bgm_playlist_order_'+signature)
    selected = [files[i] for i in order]
    st.session_state['bgm_playlist_missing'] = not selected and bgm_enabled
    if bgm_enabled:
        cache = st.session_state.setdefault('bgm_playlist_validated', {})
        try:
            for item in selected:
                digest = hashlib.sha256(item.getbuffer()).hexdigest()
                if (item.name,digest) not in cache:
                    bgm_service.validate_bgm_upload(item.name,item)
                    cache[(item.name,digest)] = True
        except (bgm_service.BgmUploadError,bgm_service.BgmServiceError) as exc:
            st.error(str(exc))
            st.session_state['bgm_playlist_missing'] = True
            return None
    return selected or None
