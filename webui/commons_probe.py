"""Explicit Commons check inside MPT; page reruns never submit requests."""
import streamlit as st
from app.services.historical_archive import commons_probe as probe


def render():
    with st.expander('Wikimedia Commons · Teste independente',expanded=False):
        st.caption('Busca, metadados, download e clipe de 4 segundos. Sem chave de API, roteiro ou narração. O teste não publica vídeos nem ativa o módulo na produção.')
        query=st.text_input('Consulta do teste Commons',value='World War II aircraft 1943',max_chars=250,key='commons_probe_query')
        make_clip=st.checkbox('Gerar clipe de teste em 16:9',value=True,key='commons_probe_clip')
        st.caption('Teste técnico da integração. A política conservadora do Commons é a mesma da produção. CC BY-SA e avisos especiais exigem revisão; classificação automática não é garantia jurídica.')
        if st.button('Testar Wikimedia Commons',disabled=not query.strip(),key='commons_probe_start'):
            try:st.session_state['commons_probe_id']=probe.submit(query,make_clip)
            except ValueError as exc:st.warning(str(exc))
        result(st.session_state.get('commons_probe_id') or probe.latest())


@st.fragment(run_every=3)
def result(task_id):
    if not task_id:return
    try:
        report=probe.read(task_id)
        st.caption('ID: '+task_id+' · '+report.get('stage',''))
        if report.get('state') in {'queued','running'}:st.info('Teste em andamento. O resultado será atualizado automaticamente.')
        elif report.get('state')=='failed':st.error(report.get('error','Falha no teste'))
        elif report.get('state')=='needs_review':st.warning('Nenhuma fotografia passou pelos critérios deste teste. Confira o JSON ou experimente uma consulta mais específica.')
        elif report.get('state')=='completed':st.success('Teste concluído. Nada foi publicado.')
        if report.get('error_type'):st.caption('Detalhe técnico: '+report['error_type']+' · '+str(report.get('error_stage','')))
        if report.get('clip') and report.get('download'):
            if st.button('Concluir créditos do clipe salvo',key='commons_probe_repair',disabled=report.get('state') in {'queued','running'}):
                try:
                    probe.submit_repair(task_id)
                    st.rerun()
                except ValueError as exc:st.warning(str(exc))
            st.caption('Reutiliza a imagem e o vídeo já salvos. Não faz nova busca, download ou renderização.')
        st.button('Atualizar teste Commons',key='commons_probe_refresh')
        if report.get('candidates'):
            st.table([{'Arquivo':r['candidate']['title'],'Classificação do teste':r['classification'],'Usado no clipe':r['used_in_test']} for r in report['candidates']])
        if report.get('clip'):
            path=probe.artifact(task_id,'commons-test-clip.mp4')
            st.video(str(path))
        names=['commons-test.json','commons-test-clip.mp4','manifest.json','diagnostic-report.json','search_log.json','sources_and_credits.json','sources_and_credits.md','commons-license-audit.json','commons-publication-review.json','historical-image-credits.txt','youtube-description-with-credits.txt']
        for name in names:
            try:path=probe.artifact(task_id,name)
            except ValueError:continue
            st.download_button('Baixar '+name,path.read_bytes(),file_name=name,key='commons_probe_download_'+name)
        st.caption('Pasta do teste: '+str(probe.folder(task_id)))
    except (ValueError,OSError) as exc:st.warning(str(exc))
