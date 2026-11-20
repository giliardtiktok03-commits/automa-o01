"""AI33PRO voice selection; read-only catalog calls only after explicit clicks."""
import hashlib
import streamlit as st
from app.config import config
from app.services.ai33.provider import api_key
from app.services.ai33.client import AI33Error
from app.services.ai33.tts import SpeechClient,voice_id,PREFIX


def save_local(group,key,value):
    target=getattr(config,group)
    if config.snapshot_config_with_pending(target).get(key)!=value:
        config.update_config_nonblocking(target,key,value)
        config.try_save_config()


def render(set_config,*,key_prefix='ai33_voice',default_voice='',set_default=True):
    settings=config.snapshot_config_with_pending(config.app)
    with st.expander('AI33PRO · Chave e catálogo de vozes',expanded=True):
        key=st.text_input('Chave da API AI33PRO',value=api_key(settings),type='password',key=key_prefix+'_key')
        # One existing AI33 key serves images and narration; don't add a second credential.
        set_config('app','ai33_api_key',key.strip())
        st.caption('Reutiliza a chave AI33PRO existente. A conta precisa permitir API e ter créditos. Consultar vozes não solicita narração; gerar voz pode consumir saldo.')
        search=st.text_input('Buscar voz por nome, idioma ou ID',value='English',key=key_prefix+'_search')
        scope=hashlib.sha256((key.strip()+'\n'+search).encode()).hexdigest()
        if st.session_state.get(key_prefix+'_scope')!=scope:
            st.session_state[key_prefix+'_scope']=scope
            st.session_state.pop(key_prefix+'_catalog',None)
            st.session_state[key_prefix+'_page']=1
        load=st.button('Carregar vozes AI33PRO',disabled=not key.strip(),key=key_prefix+'_load')
        next_page=False
        catalog=st.session_state.get(key_prefix+'_catalog',{})
        if catalog.get('has_more'):next_page=st.button('Próxima página de vozes',key=key_prefix+'_next')
        if load or next_page:
            try:
                page=st.session_state.get(key_prefix+'_page',1)+(1 if next_page else 0)
                if load:page=1
                result=SpeechClient(key.strip()).voices(search,page)
                st.session_state[key_prefix+'_catalog']=result;st.session_state[key_prefix+'_page']=page
                catalog=result;st.success('Catálogo consultado. Nenhuma narração foi solicitada.')
            except AI33Error as exc:st.error(str(exc))
        rows=catalog.get('voices',[])
        saved=str(default_voice or settings.get('ai33_tts_voice_id') or '').removeprefix(PREFIX)
        selected=saved
        if rows:
            options=[r['voice_id'] for r in rows]
            labels={r['voice_id']:r['name']+' · '+r['language']+' · '+r['voice_id'] for r in rows}
            if saved and saved not in options:options.insert(0,saved);labels[saved]=saved+' · voz salva'
            selected=st.selectbox('Voz AI33PRO',options,index=options.index(saved) if saved in options else 0,
                format_func=lambda k:labels.get(k,k),key=key_prefix+'_voice_'+str(st.session_state.get(key_prefix+'_page',1)))
        manual=st.text_input('Voice ID AI33PRO — pode colar o ID do painel',value=selected,key=key_prefix+'_manual_'+hashlib.sha256(selected.encode()).hexdigest()[:12],placeholder='elevenlabs_... ou minimax_...')
        st.caption('O ID precisa incluir o prefixo retornado pela API. A voz escolhida na Skill é salva por canal. Não há escolha aleatória automática nesta etapa.')
        limit=st.number_input('Teto local de caracteres por nova solicitação',min_value=100,max_value=1_000_000,
            value=int(settings.get('ai33_tts_max_characters',50000)),step=100,key=key_prefix+'_limit')
        set_config('app','ai33_tts_max_characters',int(limit))
        st.caption('Solicita áudio e transcrição temporizada no mesmo pedido. Confira o consumo no painel AI33PRO; o MPT não calcula um preço sem cotação oficial para essa voz.')
        value=manual.strip()
        if not value:return '',{}
        try:value=voice_id(value)
        except AI33Error as exc:st.warning(str(exc));return '',{}
        if set_default:set_config('app','ai33_tts_voice_id',value)
        full=PREFIX+value
        name=next((r['name'] for r in rows if r['voice_id']==value),value)
        return full,{full:name+' · AI33PRO'}
