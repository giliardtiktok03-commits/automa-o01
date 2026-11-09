"""Global Google Flow account, single-image test and manual recovery controls."""
import json
import time
from pathlib import Path
import streamlit as st
from app.services import google_flow, flow_browser


def render(settings,set_config):
    st.markdown('**Google Flow · Imagens no Chrome**')
    st.caption('Experimental: uma conta e uma imagem por vez. Usa a interface visível; não usa APIs internas, senhas no MPT ou rodízio de contas. O teste local valida a interface atual do Flow.')
    mode=st.selectbox('Modo Flow',['automatic','manual_import'],
        index=0 if settings.get('google_flow_access_mode','automatic')=='automatic' else 1,
        format_func=lambda value:'Automático pelo Chrome (experimental)' if value=='automatic' else 'Importar imagens manualmente',key='google_flow_mode_input')
    set_config('app','google_flow_access_mode',mode)
    profile=st.text_input('Nome do perfil local Flow',value=str(settings.get('google_flow_profile') or 'principal'),key='google_flow_profile_input').strip()
    project=st.text_input('Link do projeto Flow',value=str(settings.get('google_flow_project_url') or ''),key='google_flow_project_input').strip()
    set_config('app','google_flow_profile',profile)
    set_config('app','google_flow_project_url',project)
    models=['Nano Banana 2.1','Nano Banana 2','Nano Banana 2 Lite']
    saved=settings.get('google_flow_model','Nano Banana 2.1')
    model=st.selectbox('Modelo Flow',models,index=models.index(saved) if saved in models else 0,key='google_flow_model_input')
    set_config('app','google_flow_model',model)
    require_zero=st.checkbox('Só enviar se a tela confirmar custo de 0 créditos',value=bool(settings.get('google_flow_require_zero',True)),key='google_flow_zero_input')
    set_config('app','google_flow_require_zero',require_zero)
    timeout=st.number_input('Espera máxima Flow por imagem (segundos)',min_value=30,max_value=1800,value=int(settings.get('google_flow_timeout_seconds',900)),step=30,key='google_flow_timeout_input')
    set_config('app','google_flow_timeout_seconds',timeout)
    st.caption('Instale Google Chrome e execute PREPARAR_FLOW_WINDOWS.bat uma vez. No login, complete você mesmo as verificações do Google e abra o projeto. Depois feche apenas essa janela do perfil antes de testar. Não interaja com a janela enquanto a imagem está sendo gerada.')
    if st.button('Abrir Chrome para fazer login no Flow',disabled=not project,key='google_flow_connect'):
        try:
            result=flow_browser.connect(profile,project)
            st.session_state.google_flow_login_result=str(result)
            st.info('Chrome normal aberto. Faça login no Google, confirme acesso ao Flow e feche essa janela para liberar o teste.')
        except (ValueError,OSError) as exc:st.error(str(exc))
    login_result=st.session_state.get('google_flow_login_result')
    if login_result and Path(login_result).exists():
        login_state=json.loads(Path(login_result).read_text(encoding='utf-8'))
        if login_state.get('status')=='closed':st.caption('Janela do perfil fechada. O próximo teste verificará se a sessão está pronta.')
        else:st.warning(str(login_state.get('error') or 'Não foi possível abrir o perfil Chrome.'))
    if st.button('Testar envio automático de 1 imagem',disabled=not project or mode!='automatic',key='google_flow_test'):
        previous=st.session_state.get('google_flow_test_request')
        if previous and not Path(previous).with_suffix('.result.json').exists():
            st.warning('Já existe teste sem resultado confirmado. Confira o Chrome antes de enviar outro.')
        else:
            try:
                request=flow_browser.start_test(profile,project,require_zero,model=model)
                # Test uses the configured model; its request is written before launching.
                st.session_state.google_flow_test_request=str(request)
                st.session_state.google_flow_test_started=time.time()
                st.info('Teste iniciado no Chrome. Ao concluir, clique em Atualizar resultado do teste.')
            except (ValueError,OSError) as exc:st.error(str(exc))
    st.button('Atualizar resultado do teste',key='google_flow_refresh')
    request=st.session_state.get('google_flow_test_request')
    if request:
        path=Path(request)
        result=path.with_suffix('.result.json')
        if result.exists():
            state=json.loads(result.read_text(encoding='utf-8'))
            st.caption('Pedido enviado ao Flow: ' + ('sim — confira o projeto antes de repetir' if state.get('submitted') is True else 'não' if state.get('submitted') is False else 'não confirmado — confira o projeto'))
            if state.get('status')=='ready':
                st.success('Imagem recebida pelo navegador. Confira se o resultado corresponde ao pedido.')
                st.image(str(path.with_suffix('.png')))
            elif state.get('status')=='refused':st.warning('Flow recusou o pedido. O teste não foi repetido.')
            else:st.warning(str(state.get('error') or 'Teste interrompido; revise antes de outro envio.'))
            diagnostic=path.with_suffix('.diagnostic.json')
            if diagnostic.exists():
                st.download_button('Baixar diagnóstico do teste Flow',data=diagnostic.read_bytes(),file_name='diagnostico-flow.json',mime='application/json',key='google_flow_diagnostic_download')
        else:st.info('Aguardando o teste existente; não foi solicitado outro automaticamente.')
    st.markdown('**Prompts e recuperação por importação**')
    st.caption('As imagens já importadas são reutilizadas. Se o navegador enviar um pedido e o resultado ficar incerto, baixe a imagem no Flow e importe aqui; o MPT não repete esse envio.')
    task_id=st.text_input('ID do projeto MPT para prompts/importação',key='google_flow_task_id').strip()
    if not task_id:return
    try:
        folder=google_flow.project(task_id)
        requests=google_flow.read_requests(folder)['scenes']
        st.download_button('Baixar prompts das cenas (.md)',data=(folder/'flow_prompts.md').read_bytes(),file_name='flow_prompts.md',mime='text/markdown',key='google_flow_export_md')
        st.download_button('Baixar lista de cenas (.json)',data=(folder/'requests.json').read_bytes(),file_name='flow_prompts.json',mime='application/json',key='google_flow_export_json')
        if not requests:
            st.info('Nenhuma cena pendente de imagem neste projeto.')
            return
        entries={item['scene_id']:item for item in requests}
        scene_id=st.selectbox('Cena a importar',list(entries),format_func=lambda key:f"Cena {key:03d} · {entries[key]['status']}",key='google_flow_scene_select')
        st.code(entries[scene_id]['prompt'],language=None)
        file=st.file_uploader('Imagem gerada no Flow para esta cena',type=['png','jpg','jpeg','webp'],key='google_flow_import_file')
        if st.button('Importar e validar imagem da cena',disabled=file is None,key='google_flow_import'):
            target=google_flow.import_image(task_id,scene_id,file.getvalue())
            st.success('Imagem validada e salva. Use Retomar projeto com o mesmo ID.')
            st.image(str(target))
    except (ValueError,OSError,KeyError) as exc:st.warning(str(exc))
