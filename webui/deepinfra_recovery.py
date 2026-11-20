"""Manual DeepInfra image recovery controls inside the existing resume panel."""
import streamlit as st
from filelock import Timeout
from app.services import deepinfra_recovery,webui_task


def render(task_id,limit,*,deepinfra_unlimited=False,grok_unlimited=False):
    if not task_id:return
    try:rows=deepinfra_recovery.failures(task_id)
    except (ValueError,OSError,KeyError):return  # Incomplete/invalid input; main Check button explains it.
    if not rows:return
    with st.expander('DeepInfra · Recuperar imagem com erro HTTP',expanded=True):
        st.warning('O servidor recusou ou falhou no pedido. Uma nova tentativa pode consumir saldo, inclusive se o pedido anterior tiver sido processado. Confira o histórico DeepInfra antes de autorizar.')
        for row in rows:
            token=f"{task_id}_{row['scene_id']}_{row['request_id']}"
            st.write(f"Cena {row['scene_id']} · HTTP {row['http_status']}")
            visual=st.checkbox('Usar somente a descrição visual, sem enviar a narração completa',value=True,key='deepinfra_retry_visual_'+token)
            approved=st.checkbox('Autorizar uma única nova solicitação desta imagem',key='deepinfra_retry_approve_'+token)
            if st.button('Liberar nova tentativa desta cena',key='deepinfra_retry_'+token,disabled=not approved):
                try:
                    if webui_task.is_generation_active(task_id):raise ValueError('Aguarde o projeto parar antes de liberar uma nova tentativa.')
                    deepinfra_recovery.authorize(task_id,**{k:row[k] for k in ('scene_id','request_id')},limit=limit,
                        deepinfra_unlimited=deepinfra_unlimited,grok_unlimited=grok_unlimited,visual_only=visual)
                    st.success('Uma nova tentativa foi liberada. Agora clique em Retomar projeto salvo. O áudio e as cenas prontas serão reutilizados.')
                except (ValueError,OSError,KeyError,Timeout) as exc:st.error(str(exc))
