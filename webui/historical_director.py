"""Historical Documentary Director workspace, entirely inside the Skills block."""
import html
import json
import time
import streamlit as st
from app.models.autopilot import ChannelProfile
from app.models.historical_director import Request, VideoProduction
from app.models.llm_provider import LLM_PROVIDER_REGISTRY
from app.services.autopilot import editorial, worker
from app.services.historical_director import images, production
from app.services.historical_director.library import SKILL_ID

LABELS={'analyzing':'Analisando referência','selection':'Aguardando seleção','ready':'Pronto para iniciar',
        'running':'Produzindo pacotes','paused':'Pausado','completed':'Lote concluído',
        'queued':'Aguardando','blocked':'Requer revisão','failed':'Falhou','cancelled':'Cancelado'}
COLORS={1:'#2563eb',2:'#7c3aed',3:'#d97706',4:'#0891b2',5:'#a16207',6:'#059669'}


def section(number,title):
    st.markdown(f'<div class="mpt-stage-heading" style="--mpt-stage-accent:{COLORS[number]}">'
                f'<span class="mpt-stage-heading__number">00.{number}</span> · {html.escape(title)}</div>',
                unsafe_allow_html=True)


def reference_text(uploaded):
    if uploaded is None:return ''
    data=uploaded.getvalue()
    if len(data)>500000:raise ValueError('Roteiro de referência excede 500 KB')
    try:text=data.decode('utf-8-sig')
    except UnicodeError:raise ValueError('Salve o roteiro de referência em UTF-8') from None
    if len(text)>120000 or '\x00' in text:raise ValueError('Use até 120 mil caracteres de texto válido')
    return text


def render(params,repository,*,autostart=True,on_settings=None):
    active=bool(params is not None and params.skills_enabled and SKILL_ID in params.skill_ids)
    with st.expander('Historical Documentary Director · Espaço da Skill',expanded=active,key='director_panel'):
        st.caption('Canal → referências → ângulos → pesquisa → seleção → fila e pacotes. Tudo neste bloco da Skill.')
        st.caption('Entrega por canal: pacote editorial, narração ou vídeo 16:9. Publicação permanece desligada.')
        if autostart and repository.enabled():worker.ensure_started()
        if active:
            profile=_channel_setup(repository,params)
            if profile is not None:_new_batch(repository,profile,autostart=autostart,on_settings=on_settings)
        else:
            st.info('Para criar novos pacotes, ative as Skills editoriais e selecione Historical Documentary Director acima. Os lotes já enviados continuam disponíveis abaixo.')
        _batches(repository,autostart)
    return True


def _channel_setup(repo,params):
    section(1,'Canal e permissões')
    channels=repo.channels()
    options=[c['channel_id'] for c in channels]+['__new__']
    pending=st.session_state.pop('director_pending_channel',None)
    if pending in options:st.session_state['director_channel']=pending
    if st.session_state.get('director_channel') not in options:
        st.session_state['director_channel']=options[0]
    selected=st.selectbox('Canal para a direção histórica',options,
        format_func=lambda x:'Cadastrar novo canal' if x=='__new__' else next(c['name'] for c in channels if c['channel_id']==x),key='director_channel')
    old=next((c for c in channels if c['channel_id']==selected),None)
    values={k:v for k,v in old.items() if k!='version'} if old else ChannelProfile(channel_id='new',name='Novo canal').model_dump()
    profile=ChannelProfile.model_validate(values)
    ready=old is not None and SKILL_ID in profile.skill_ids and profile.auto_editorial
    with st.expander('Configurar canal, Skills e autorização',expanded=not ready,key='director_channel_editor_'+selected):
        with st.form('director_channel_form_'+selected):
            left,right=st.columns(2)
            identifier=left.text_input('Identificador do canal (sem @)',value=profile.channel_id if old else '',disabled=old is not None,key='director_channel_id_'+selected)
            name=right.text_input('Nome do canal',value=profile.name if old else '',key='director_channel_name_'+selected)
            language=left.text_input('Idioma do canal',value=profile.language,key='director_channel_language_'+selected)
            minutes=right.number_input('Duração desejada (minutos)',min_value=3,max_value=30,value=profile.target_minutes,key='director_channel_minutes_'+selected)
            niche=st.text_input('Nicho do canal',value=profile.niche,key='director_channel_niche_'+selected)
            sync=st.checkbox('Salvar neste canal as Skills selecionadas neste bloco',value=profile.skill_ids!=list(params.skill_ids),key='director_sync_skills_'+selected)
            st.caption('Seleção atual: '+' → '.join(params.skill_ids)+' · a primeira tem prioridade.')
            st.caption('Skills salvas: '+(' → '.join(profile.skill_ids) or 'nenhuma'))
            permission=st.checkbox('Autorizar pesquisa e roteiro automáticos para este canal',value=profile.auto_editorial,key='director_channel_permission_'+selected)
            st.caption('Salvar esta autorização não inicia chamadas de IA. O botão de pesquisar ou de retomar a fila inicia a execução e pode consumir saldo.')
            with st.expander('Avançado · modelos e fontes da pesquisa'):
                backends=['openai','public_login']
                backend=st.selectbox('Modo de pesquisa',backends,index=backends.index(profile.research_backend),
                    format_func=lambda x:'API OpenAI com busca web (modo atual)' if x=='openai' else 'Pesquisa pública + ChatGPT/Codex por login',key='director_research_backend_'+selected)
                research_model=st.text_input('Modelo OpenAI para pesquisa e Blueprint',value=profile.research_model,key='director_channel_research_model_'+selected)
                domains=st.text_area('Restringir pesquisa a estes domínios (opcional, um por linha)',value='\n'.join(profile.research_domains),key='director_channel_domains_'+selected)
                providers=['current',*[p.provider_id for p in LLM_PROVIDER_REGISTRY]]
                provider=st.selectbox('Provedor do roteiro',providers,index=providers.index(profile.script_provider) if profile.script_provider in providers else 0,
                    format_func=lambda x:'Usar provedor atual do MPT' if x=='current' else next(p.default_label for p in LLM_PROVIDER_REGISTRY if p.provider_id==x),key='director_channel_provider_'+selected)
                model=st.text_input('Modelo do roteiro (vazio usa o configurado no provedor)',value=profile.script_model,key='director_channel_script_model_'+selected)
                st.caption('No modo público, a descoberta usa o índice da Wikipédia e lê referências externas; pesquisa e texto usam ChatGPT/Codex por login, sem chave OpenAI. Exige provedor por login conectado e está sujeito aos limites da conta. A análise visual de thumbnails ainda exige API e fica bloqueada nesse modo. O campo de modelo OpenAI só vale no modo API.')
            save=st.form_submit_button('Salvar canal desta Skill')
        if save:
            try:
                update=dict(channel_id=identifier.strip(),name=name,language=language,niche=niche,target_minutes=int(minutes),
                    skill_ids=list(params.skill_ids) if sync else profile.skill_ids,auto_editorial=permission,
                    research_model=research_model,research_backend=backend,research_domains=[d.strip() for d in domains.splitlines() if d.strip()],script_provider=provider,script_model=model)
                updated=ChannelProfile.model_validate({**profile.model_dump(),**update})
                repo.save_channel(updated,expected_version=old['version'] if old else 0)
                st.session_state['director_pending_channel']=updated.channel_id
                st.rerun()
            except ValueError as exc:st.error(str(exc))
    if old is None:
        st.info('Cadastre e salve o canal acima. Depois, as referências aparecerão aqui.')
        return None
    if SKILL_ID not in profile.skill_ids:
        st.warning('Salve a seleção de Skills acima para vincular Historical Documentary Director a este canal.')
    elif not profile.auto_editorial:
        st.warning('Autorize pesquisa e roteiro no formulário acima antes de iniciar a pesquisa.')
    else:
        st.caption(f'{profile.name} · {profile.language} · {profile.target_minutes} minutos · canal pronto para esta Skill.')
    return profile


def _new_batch(repo,profile,*,autostart=True,on_settings=None):
    channel_id=profile.channel_id
    saved=repo.director_profile(channel_id)
    defaults=Request(title='Defaults',**saved)
    section(2,'Referências')
    title=st.text_input('Título de referência',max_chars=300,key='director_reference_title_'+channel_id)
    source_mode=st.radio('Roteiro de referência (opcional)',['Colar texto','Enviar arquivo'],horizontal=True,key='director_reference_mode_'+channel_id)
    pasted=st.text_area('Colar roteiro de referência',max_chars=120000,height=160,key='director_reference_text_'+channel_id) if source_mode=='Colar texto' else ''
    script_file=st.file_uploader('Arquivo de referência TXT ou MD (UTF-8)',type=['txt','md'],max_upload_size=1,key='director_reference_file_'+channel_id) if source_mode=='Enviar arquivo' else None
    visual=st.checkbox('Analisar thumbnails de referência',value=defaults.thumbnail_reference_enabled,key='director_visual_'+channel_id)
    with st.expander('Limite dos arquivos de referência'):
        max_mb=st.number_input('Limite por thumbnail (MB)',min_value=1,max_value=20,value=defaults.max_image_mb,key='director_image_mb_'+channel_id)
    uploaded=st.file_uploader('Até 3 thumbnails de referência (JPG, PNG, WebP)',type=['jpg','jpeg','png','webp'],accept_multiple_files=True,max_upload_size=int(max_mb),key='director_thumbnails_'+channel_id)
    st.caption('O roteiro serve para análise, não como prova factual. Use o X para remover arquivos. Com análise visual desligada, as imagens não são enviadas ao modelo.')
    if len(uploaded or [])>3:st.error('Envie no máximo 3 thumbnails de referência')
    elif uploaded:
        previews=st.columns(len(uploaded))
        for target,f in zip(previews,uploaded):
            try:
                ref=images.store(f.getvalue(),max_mb=int(max_mb));target.image(images.read(ref),width=220,caption=f.name)
            except ValueError as exc:st.error(str(exc))
    section(3,'Ângulos e direção visual')
    angle_enabled=st.checkbox('Angle Intelligence — propor novos ângulos',value=defaults.angle_enabled,key='director_angle_enabled_'+channel_id)
    mode='manual';multiple=False;top_n=1
    if angle_enabled:
        mode=st.radio('Seleção de ângulos',['manual','automatic'],index=['manual','automatic'].index(defaults.selection_mode),horizontal=True,
            format_func=lambda x:'Manual' if x=='manual' else 'Automática',key='director_mode_'+channel_id)
        if mode=='automatic':
            multiple=st.checkbox('Autorizar múltiplos vídeos no modo automático',value=defaults.automatic_multiple,key='director_multiple_'+channel_id)
            if multiple:top_n=st.number_input('Quantidade no automático',min_value=1,max_value=5,value=defaults.automatic_top_n,key='director_top_n_'+channel_id)
    st.caption('Sem mudança de ângulo: mantém o título original e cria um pacote. No automático: um pacote por padrão; múltiplos exigem autorização explícita.')
    with st.expander('Perfil editorial e visual do canal'):
        central=st.text_area('Ângulo central do canal',value=defaults.central_angle,max_chars=1000,key='director_central_'+channel_id)
        identity=st.text_area('Identidade visual do canal',value=defaults.visual_identity,max_chars=1500,key='director_identity_'+channel_id)
    section(4,'Pesquisa e revisão')
    if on_settings is not None:
        st.button('Configurar acesso aos provedores',key='director_provider_access',on_click=on_settings,args=('llm',))
    with st.expander('Avançado · análise visual, pesos e tratamento de falhas'):
        vision_model=st.text_input('Modelo OpenAI com visão para referências',value=defaults.vision_model,key='director_vision_model_'+channel_id)
        st.caption('Pesos editoriais: devem somar 100. Não representam probabilidade de viralização.')
        weights={}
        columns=st.columns(5)
        for column,(name,label) in zip(columns,[('curiosity','Curiosidade'),('originality','Originalidade'),('thumbnail','Thumbnail'),('retention','Retenção'),('sources','Fontes verificáveis')]):
            weights[name]=column.number_input(label,min_value=0,max_value=100,value=getattr(defaults.weights,name),key='director_weight_'+channel_id+'_'+name)
        policy=st.selectbox('Quando um item falhar',['pause_queue','skip'],index=['pause_queue','skip'].index(defaults.on_failure),
            format_func=lambda x:'Pausar fila de documentários (padrão)' if x=='pause_queue' else 'Registrar falha e pular para o próximo',key='director_failure_'+channel_id)
        new_version=st.checkbox('Criar uma nova versão explícita do lote, mesmo com referências iguais',key='director_new_version_'+channel_id)
    st.caption('A pesquisa busca fontes e confere os trechos. Cada ângulo terá sua própria pesquisa e revisão. Modo do canal: '+('pesquisa pública + login ChatGPT/Codex (limites da conta)' if profile.research_backend=='public_login' else 'API OpenAI (pode consumir saldo)')+'.')
    production_options=_production_options(defaults.production,channel_id,login_mode=profile.research_backend=='public_login')
    save=st.button('Salvar preferências da Skill para este canal',key='director_save_profile_'+channel_id)
    ready=SKILL_ID in profile.skill_ids and profile.auto_editorial
    submit=st.button('Pesquisar referência e analisar ângulos',type='primary',disabled=not ready,key='director_submit_'+channel_id)
    if save or submit:
        try:
            options=dict(angle_enabled=angle_enabled,selection_mode=mode,automatic_multiple=multiple,automatic_top_n=int(top_n),
                thumbnail_reference_enabled=visual,central_angle=central,visual_identity=identity,weights=weights,vision_model=vision_model,max_image_mb=int(max_mb),on_failure=policy,production=production_options)
            if save:
                repo.save_director_profile(channel_id,options);st.success('Preferências salvas somente para este canal.')
            if submit:
                request=Request(title=title,reference_script=pasted if source_mode=='Colar texto' else reference_text(script_file),
                    thumbnails=images.upload([f.getvalue() for f in uploaded or []],max_mb=int(max_mb)),**options)
                snapshot=editorial.prepare(profile)
                from app.services.historical_director.runner import check_research_options
                check_research_options(request,snapshot)
                batch,created=repo.create_director_batch(request,snapshot,new_version=new_version)
                repo.set_enabled(True)
                st.session_state['autopilot_worker_pending_enabled']=True
                if autostart:worker.ensure_started()
                st.success('Pesquisa enviada para execução. Acompanhe a seleção e a fila abaixo.' if created else 'Este lote já existe; acompanhe abaixo. Nenhuma análise duplicada foi criada.')
        except (ValueError,OSError) as exc:st.error(str(exc))


def _production_options(defaults,channel_id,*,login_mode=False):
    from pathlib import Path
    from app.utils import utils
    with st.expander('Produção · narração, imagens, legendas e música',expanded=defaults.mode!='editorial'):
        modes=['editorial','narration','video']
        labels={'editorial':'Somente pacote editorial','narration':'Pacote + narração','video':'Pacote + narração + vídeo completo'}
        mode=st.selectbox('Entrega de cada ângulo',modes,index=modes.index(defaults.mode),format_func=labels.get,key='director_output_'+channel_id)
        st.caption('Estas opções ficam salvas por canal e congeladas no lote. Alterações valem para novos lotes. A geração começa depois da aprovação editorial automática.')
        if mode=='editorial':return defaults.model_copy(update={'mode':mode}).model_dump()
        voice=st.text_input('Voz da narração (identificador do MPT)',value=defaults.voice_name,key='director_voice_'+channel_id)
        st.caption('Use o identificador de uma voz já configurada no MPT. Exemplo em inglês: en-US-ChristopherNeural-Male. Credenciais continuam nas configurações existentes.')
        rate=st.number_input('Velocidade da voz',min_value=0.5,max_value=2.0,value=float(defaults.voice_rate),step=0.05,key='director_voice_rate_'+channel_id)
        subtitles=st.checkbox('Gerar legendas',value=defaults.subtitle_enabled,key='director_subtitles_'+channel_id)
        provider=st.selectbox('Temporização das legendas',['edge','whisper'],index=['edge','whisper'].index(defaults.subtitle_provider),key='director_subtitle_provider_'+channel_id)
        st.caption('Edge usa a temporização retornada pela voz. Vozes sem essa temporização precisam do Whisper configurado no MPT.')
        values={**defaults.model_dump(),'mode':mode,'voice_name':voice,'voice_rate':rate,'subtitle_enabled':subtitles,'subtitle_provider':provider}
        if mode=='video':
            source=st.selectbox('Origem das cenas',['mixed','deepinfra_image'],index=['mixed','deepinfra_image'].index(defaults.video_source),
                format_func=lambda x:'Bancos de vídeo + DeepInfra quando necessário' if x=='mixed' else 'Somente imagens DeepInfra',key='director_media_source_'+channel_id)
            pexels=st.checkbox('Usar Pexels',value=defaults.use_pexels,key='director_pexels_'+channel_id)
            pixabay=st.checkbox('Usar Pixabay',value=defaults.use_pixabay,key='director_pixabay_'+channel_id)
            models=['stabilityai/sdxl-turbo','black-forest-labs/FLUX-1-schnell','PrunaAI/p-image']
            model=st.selectbox('Modelo DeepInfra da Skill',models,index=models.index(defaults.deepinfra_model),
                format_func=lambda x:'PrunaAI P-Image' if x=='PrunaAI/p-image' else x,key='director_image_model_'+channel_id)
            unlimited=st.checkbox('DeepInfra sem limite de imagens neste lote',value=defaults.deepinfra_unlimited,key='director_image_unlimited_'+channel_id)
            limit=st.number_input('Limite TOTAL de imagens por vídeo',min_value=0,max_value=120,value=defaults.image_limit,disabled=unlimited,key='director_image_limit_'+channel_id)
            st.caption('Sem limite pode consumir saldo para completar todas as cenas. Solicitações anteriores contam no limite de cada vídeo.')
            validation=st.checkbox('Validar visualmente os vídeos dos bancos',value=defaults.visual_validation,key='director_visual_validation_'+channel_id)
            if login_mode:
                st.info('A pesquisa por login dispensa a chave OpenAI na parte editorial. A validação visual dos bancos continua usando API OpenAI. Para produzir vídeo sem essa chave, escolha somente imagens DeepInfra e desative a validação visual. O DeepInfra mantém seu próprio consumo.')
            fonts=sorted(p.name for p in Path(utils.font_dir()).iterdir() if p.suffix.lower() in {'.ttf','.ttc','.otf'})
            if defaults.font_name not in fonts:fonts.insert(0,defaults.font_name)
            font=st.selectbox('Fonte das legendas',fonts,index=fonts.index(defaults.font_name),key='director_font_'+channel_id)
            music=st.checkbox('Usar música da biblioteca local do MPT',value=defaults.music_enabled,key='director_music_'+channel_id)
            volume=st.number_input('Volume da música',min_value=0.0,max_value=1.0,value=float(defaults.music_volume),step=0.05,key='director_music_volume_'+channel_id)
            st.caption('Saída 16:9. Zoom e montagem usam o fluxo existente. Esta fase usa música local e não gera efeitos sonoros ou thumbnail final; o pacote inclui os três briefings de thumbnail.')
            values.update(video_source=source,use_pexels=pexels,use_pixabay=pixabay,deepinfra_model=model,
                deepinfra_unlimited=unlimited,image_limit=int(limit),visual_validation=validation,
                font_name=font,music_enabled=music,music_volume=volume)
        return VideoProduction.model_validate(values).model_dump()


def _select(repo,batch,result):
    request=Request.model_validate_json(batch['request'])
    if not request.angle_enabled:
        st.info('Mudança de ângulo desativada: será produzido um pacote com o título original.')
        return
    angles=result['analysis']['alternatives'];eligible=[a['angle_id'] for a in angles if a['eligible']]
    st.write('Tema: '+result['analysis']['theme'])
    st.write('Ângulo de referência: '+result['analysis']['reference_angle'])
    st.write('Estrutura de referência: '+' → '.join(result['analysis']['reference_structure']))
    if result['analysis'].get('reference_limitations'):st.caption(' · '.join(result['analysis']['reference_limitations']))
    st.caption('A pontuação é avaliação editorial; não representa probabilidade de viralização. As fontes serão pesquisadas novamente para cada ângulo produzido.')
    manual=request.selection_mode=='manual'
    if manual:
        if st.button('Selecionar todos os 5',key='director_all_'+batch['batch_id'],disabled=len(eligible)!=5):
            for a in angles:st.session_state['director_pick_'+batch['batch_id']+'_'+a['angle_id']]=a['eligible']
        if st.button('Limpar seleção',key='director_clear_'+batch['batch_id']):
            for a in angles:st.session_state['director_pick_'+batch['batch_id']+'_'+a['angle_id']]=False
    chosen=[]
    for angle in angles:
        with st.container(border=True):
            if manual:
                picked=st.checkbox(angle['name']+' · '+angle['title_en'],disabled=not angle['eligible'],key='director_pick_'+batch['batch_id']+'_'+angle['angle_id'])
                if picked and angle['eligible']:chosen.append(angle['angle_id'])
            else:st.write('**'+angle['name']+' · '+angle['title_en']+'**')
            st.caption(angle['title_pt'])
            if angle.get('title_local') and angle['title_local'] not in {angle['title_en'],angle['title_pt']}:st.caption(angle['title_local'])
            st.write(angle['core_question'])
            st.caption(f"Score: {angle['editorial_score']} · Framework {angle['story_framework']} · "+('Elegível' if angle['eligible'] else 'Não elegível'))
            st.caption(' · '.join(angle['eligibility_reasons']))
            with st.expander('Detalhes · '+angle['angle_id']):st.json(angle)
    if manual:
        key='director_selection_order_'+batch['batch_id']
        prior=st.session_state.get(key,[])
        st.session_state[key]=[x for x in prior if x in chosen]+[x for x in chosen if x not in prior]
        order=st.multiselect('Ordem dos ângulos selecionados (remova e reinsira para reordenar)',chosen,key=key)
        if st.button(f'Adicionar {len(order)} vídeos à fila',disabled=not order,key='director_enqueue_'+batch['batch_id']):
            try:
                if set(order)!=set(chosen):raise ValueError('Mantenha todos os ângulos marcados na ordem escolhida')
                ids,created=repo.enqueue_director_angles(batch['batch_id'],order)
                st.success(f'{len(ids)} pacotes na fila.' if created else 'Seleção já enfileirada; nenhum item duplicado.')
                st.rerun()
            except ValueError as exc:st.error(str(exc))
    else:
        st.info('Seleção automática: '+', '.join(result['recommended_ids'][:request.automatic_top_n])+' · será enfileirada automaticamente com a execução ativa neste bloco.')


@st.fragment(run_every=3)
def _batches(repo,autostart=True):
    from webui.autopilot import render_worker_control
    batches=repo.director_batches(limit=10)
    section(5,'Ângulos e seleção')
    pending_selection=[batch for batch in batches if batch['state']=='selection' and batch['analysis']]
    if not pending_selection:st.caption('As propostas aparecerão aqui após a pesquisa e a revisão. No modo automático, a seleção é enviada à fila diretamente.')
    for batch in pending_selection:
        request=Request.model_validate_json(batch['request'])
        with st.expander('Selecionar ângulos · '+request.title,expanded=True,key='director_selection_'+batch['batch_id']):
            _select(repo,batch,json.loads(batch['analysis']))
    section(6,'Fila e pacotes')
    render_worker_control(repo,autostart=autostart)
    if not batches:st.caption('Nenhum lote enviado. Comece pelas referências e pelo botão de pesquisa acima.')
    for batch in batches:
        request=Request.model_validate_json(batch['request'])
        with st.expander(request.title+' · '+LABELS.get(batch['state'],batch['state']),key='director_batch_'+batch['batch_id']):
            st.caption('Lote '+batch['batch_id']+' · '+json.loads(batch['snapshot'])['channel']['name'])
            if batch['error']:st.warning(batch['error'])
            if batch['analysis']:
                result=json.loads(batch['analysis'])
                st.download_button('Exportar análise e IDs (.json)',json.dumps({'batch':batch,'analysis':result},ensure_ascii=False,indent=2),
                    file_name='historical-analysis-'+batch['batch_id']+'.json',mime='application/json',key='director_analysis_download_'+batch['batch_id'])
            items=repo.director_items(batch['batch_id'])
            production_items=[i for i in items if i['role']=='production']
            completed=sum(i['state']=='completed' for i in production_items)
            st.caption(f'Pacotes concluídos: {completed}/{len(production_items)} · produção de um item por vez')
            if batch['state']!='completed':
                if st.button('Iniciar fila / Retomar',key='director_resume_'+batch['batch_id']):
                    try:
                        repo.resume_director(batch['batch_id']);repo.set_enabled(True)
                        st.session_state['autopilot_worker_pending_enabled']=True
                        if autostart:worker.ensure_started()
                        st.rerun()
                    except ValueError as exc:st.error(str(exc))
                if st.button('Pausar após a etapa atual',key='director_pause_'+batch['batch_id']):
                    repo.pause_director(batch['batch_id']);st.rerun()
                if st.button('Encerrar lote / Cancelar pendentes',key='director_cancel_batch_'+batch['batch_id']):
                    repo.cancel_director_batch(batch['batch_id']);st.rerun()
            pending=[i for i in production_items if i['state']=='queued']
            if len(pending)>1:
                labels={i['task_id']:i['title'] for i in pending};key='director_pending_order_'+batch['batch_id']
                prior=st.session_state.get(key,list(labels))
                st.session_state[key]=[x for x in prior if x in labels]+[x for x in labels if x not in prior]
                order=st.multiselect('Ordem dos itens pendentes',list(labels),format_func=lambda x:labels[x],key=key)
                if st.button('Salvar ordem dos pendentes',key='director_reorder_'+batch['batch_id']):
                    try:repo.reorder_director(batch['batch_id'],order);st.rerun()
                    except ValueError as exc:st.error(str(exc))
            for item in items:
                _item(repo,item,batch)

    from webui.autopilot import render_editorial_results
    render_editorial_results(repo,director=True)


def _item(repo,item,batch):
    st.write(('**Análise**' if item['role']=='analysis' else f"**{item['position']}. {item['title']}**")+' · '+LABELS.get(item['state'],item['state']))
    stages=repo.stages(item['task_id'])
    current=next((s['name'] for s in stages.values() if s['state']=='running'),None)
    stage_labels={'director_narration':'Gerando narração e legendas','director_video':'Selecionando cenas e montando vídeo','director_media_export':'Salvando relatório de mídia'}
    if current:st.caption('Etapa: '+stage_labels.get(current,current)+' · '+str(int(time.time()-item['created']))+' s desde o envio')
    if item['error']:st.warning(item['error'])
    if item['role']=='production' and item['state']=='completed' and item['result']:
        result=json.loads(item['result'])
        st.caption('Entregáveis: '+result['deliverables']['directory'])
        _media_result(result,item['task_id'])
        try:
            st.download_button('Baixar pacote completo (.zip)',production.archive(result),file_name='historical-'+item['task_id']+'.zip',mime='application/zip',key='director_package_'+item['task_id'])
        except (ValueError,OSError) as exc:st.error(str(exc))
        st.download_button('Exportar pacote e IDs (.json)',json.dumps(result,ensure_ascii=False,indent=2),file_name='historical-'+item['task_id']+'.json',mime='application/json',key='director_job_json_'+item['task_id'])
    if item['state'] in {'failed','blocked'}:
        ack=st.checkbox('Autorizar outra tentativa (pode consumir saldo)',key='director_ack_'+item['task_id'])
        if st.button('Repetir etapas pendentes',disabled=not ack,key='director_retry_'+item['task_id']):
            try:
                repo.retry_editorial(item['task_id'],acknowledge_cost=True)
                st.info('Etapas pendentes reenfileiradas. Use Retomar após revisar os demais itens com falha.');st.rerun()
            except ValueError as exc:st.error(str(exc))
    if item['state'] not in {'completed','cancelled'}:
        if st.button('Cancelar item',key='director_cancel_'+item['task_id']):
            repo.cancel_director_item(item['task_id']);st.rerun()
    if item['role']=='production' and item['state']=='queued' and not stages:
        with st.expander('Substituir referências antes de iniciar · '+item['angle_id']):
            context=json.loads(item['context']);request=Request.model_validate(context['request'])
            st.caption('Referências atuais: '+str(len(request.thumbnails))+' · revisão '+str(item['angle_version']))
            enabled=st.checkbox('Analisar novas referências',value=request.thumbnail_reference_enabled,key='director_replace_enabled_'+item['task_id'])
            uploaded=st.file_uploader('Novas thumbnails (0 a 3; vazio remove as anteriores)',type=['jpg','jpeg','png','webp'],accept_multiple_files=True,max_upload_size=request.max_image_mb,key='director_replace_images_'+item['task_id'])
            if st.button('Salvar referências deste item',key='director_replace_'+item['task_id']):
                try:
                    refs=images.upload([f.getvalue() for f in uploaded or []],max_mb=request.max_image_mb)
                    repo.replace_director_references(item['task_id'],refs,enabled);st.rerun()
                except (ValueError,OSError) as exc:st.error(str(exc))


def _media_result(result,task_id):
    media=result.get('media')
    if not media:return
    st.caption('Mídia salva em storage/tasks/'+task_id+' · publicação desligada')
    if not st.checkbox('Mostrar prévia da mídia',key='director_media_preview_'+task_id):return
    from app.services.historical_director import video_production as bridge
    try:
        folder=bridge.directory(task_id)
        bridge.verify_receipts(folder,media['narration'])
        st.audio(str(folder/'audio.mp3'))
        if media.get('video_generated'):
            final=media['video']
            if bridge.receipt(folder,final['file'])!={k:final[k] for k in ('file','bytes','sha256')}:
                raise ValueError('Vídeo final alterado')
            st.video(str(folder/final['file']))
            st.caption('Vídeo salvo em '+str(folder/final['file'])+' · decodificação verificada · não publicado')
    except (ValueError,OSError) as exc:st.error(str(exc))
