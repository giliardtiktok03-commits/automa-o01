"""Optional documentary workflow, reusing panel-00 Skills and AUTOPILOT channels."""
import json
import time
import streamlit as st
from app.models.autopilot import ChannelProfile
from app.models.historical_director import Request, Weights
from app.services.autopilot import editorial, worker
from app.services.historical_director import images, production
from app.services.historical_director.library import SKILL_ID

LABELS={'analyzing':'Analisando referência','selection':'Aguardando seleção','ready':'Pronto para iniciar',
        'running':'Produzindo pacotes','paused':'Pausado','completed':'Lote concluído',
        'queued':'Aguardando','blocked':'Requer revisão','failed':'Falhou','cancelled':'Cancelado'}


def reference_text(uploaded):
    if uploaded is None:return ''
    data=uploaded.getvalue()
    if len(data)>500000:raise ValueError('Roteiro de referência excede 500 KB')
    try:text=data.decode('utf-8-sig')
    except UnicodeError:raise ValueError('Salve o roteiro de referência em UTF-8') from None
    if len(text)>120000 or '\x00' in text:raise ValueError('Use até 120 mil caracteres de texto válido')
    return text


def render(params,repository,*,autostart=True):
    with st.expander('Historical Documentary Director · Ângulos e fila',key='director_panel'):
        active=bool(params is not None and params.skills_enabled and SKILL_ID in params.skill_ids)
        enabled=st.checkbox('Usar a Skill neste fluxo de documentários',value=active,key='director_enabled')
        st.caption('Pacotes editoriais: pesquisa independente, roteiro, descrição, tags e 3 conceitos de thumbnail. Este fluxo ainda não gera mídia nem publica vídeos.')
        if enabled:
            channels=repository.channels()
            if not channels:
                st.info('Cadastre um canal no AUTOPILOT para começar.')
            else:
                _new_batch(repository,channels)
        else:
            st.caption('O gerador habitual do MPT permanece disponível. Para desativar também as instruções editoriais no gerador manual, desmarque a Skill no painel 00. Lotes já enviados mantêm sua autorização; use Pausar para interromper a fila.')
        _batches(repository,autostart)


def _new_batch(repo,channels):
    channel_id=st.selectbox('Canal para a direção histórica',[c['channel_id'] for c in channels],
        format_func=lambda x:next(c['name'] for c in channels if c['channel_id']==x),key='director_channel')
    saved=repo.director_profile(channel_id)
    defaults=Request(title='Defaults',**saved)
    profile=ChannelProfile.model_validate({k:v for k,v in next(c for c in channels if c['channel_id']==channel_id).items() if k!='version'})
    st.caption(f'Perfil salvo: {profile.language} · {profile.target_minutes} minutos. Ajuste idioma, duração e provedor no cadastro do canal no AUTOPILOT.')
    if SKILL_ID not in profile.skill_ids:
        st.info('No painel 00, selecione Historical Documentary Director. No cadastro do canal, salve a seleção desse painel. Autorize pesquisa e roteiro para o canal.')
    with st.container(border=True):
        title=st.text_input('Título de referência',max_chars=300,key='director_reference_title_'+channel_id)
        source_mode=st.radio('Roteiro de referência (opcional)',['Colar texto','Enviar arquivo'],key='director_reference_mode_'+channel_id)
        pasted=st.text_area('Colar roteiro de referência',max_chars=120000,height=160,key='director_reference_text_'+channel_id) if source_mode=='Colar texto' else ''
        script_file=st.file_uploader('Arquivo de referência TXT ou MD (UTF-8)',type=['txt','md'],max_upload_size=1,key='director_reference_file_'+channel_id) if source_mode=='Enviar arquivo' else None
        central=st.text_area('Ângulo central do canal',value=defaults.central_angle,max_chars=1000,key='director_central_'+channel_id)
        identity=st.text_area('Identidade visual do canal',value=defaults.visual_identity,max_chars=1500,key='director_identity_'+channel_id)
        angle_enabled=st.checkbox('Angle Intelligence — propor novos ângulos',value=defaults.angle_enabled,key='director_angle_enabled_'+channel_id)
        mode='manual';multiple=False;top_n=1
        if angle_enabled:
            mode=st.radio('Seleção de ângulos',['manual','automatic'],index=['manual','automatic'].index(defaults.selection_mode),
                format_func=lambda x:'Manual' if x=='manual' else 'Automática',key='director_mode_'+channel_id)
            if mode=='automatic':
                multiple=st.checkbox('Autorizar múltiplos vídeos no modo automático',value=defaults.automatic_multiple,key='director_multiple_'+channel_id)
                if multiple:
                    top_n=st.number_input('Quantidade no automático',min_value=1,max_value=5,value=defaults.automatic_top_n,key='director_top_n_'+channel_id)
        st.caption('Se Angle Intelligence estiver desligado, o título e o ângulo originais serão mantidos e apenas um pacote será enfileirado. A escolha manual será feita após a análise.')
        visual=st.checkbox('Analisar thumbnails de referência',value=defaults.thumbnail_reference_enabled,key='director_visual_'+channel_id)
        max_mb=st.number_input('Limite por thumbnail (MB)',min_value=1,max_value=20,value=defaults.max_image_mb,key='director_image_mb_'+channel_id)
        uploaded=st.file_uploader('Até 3 thumbnails de referência (JPG, PNG, WebP)',type=['jpg','jpeg','png','webp'],accept_multiple_files=True,max_upload_size=int(max_mb),key='director_thumbnails_'+channel_id)
        st.caption('Use o X do carregador para remover ou substituir arquivos. Desativar análise mantém os anexos sem enviá-los ao modelo visual. Imagens não serão usadas como thumbnails finais.')
        vision_model=st.text_input('Modelo OpenAI com visão para referências',value=defaults.vision_model,key='director_vision_model_'+channel_id)
        st.markdown('**Pesos editoriais (devem somar 100)**')
        weights={}
        for name,label in [('curiosity','Curiosidade'),('originality','Originalidade'),('thumbnail','Thumbnail'),('retention','Retenção'),('sources','Fontes verificáveis')]:
            weights[name]=st.number_input(label,min_value=0,max_value=100,value=getattr(defaults.weights,name),key='director_weight_'+channel_id+'_'+name)
        policy=st.selectbox('Quando um item falhar',['pause_queue','skip'],index=['pause_queue','skip'].index(defaults.on_failure),
            format_func=lambda x:'Pausar fila de documentários (padrão)' if x=='pause_queue' else 'Registrar falha e pular para o próximo',key='director_failure_'+channel_id)
        st.caption('Publicação: desativada nesta entrega. A busca web e a análise visual usam a API oficial OpenAI. Texto e revisões usam o provedor salvo no canal. Chamadas podem consumir saldo.')
        new_version=st.checkbox('Criar uma nova versão explícita do lote, mesmo com referências iguais',key='director_new_version_'+channel_id)
        save=st.button('Salvar preferências da Skill para este canal',key='director_save_profile_'+channel_id)
        submit=st.button('Pesquisar referência e analisar ângulos',key='director_submit_'+channel_id)
    if len(uploaded or [])>3:st.error('Envie no máximo 3 thumbnails de referência')
    elif uploaded:
        for f in uploaded:
            # Preview only decoded, sanitized images. No provider call during a rerun.
            try:
                ref=images.store(f.getvalue(),max_mb=int(max_mb))
                st.image(images.read(ref),width=220,caption=f.name)
            except ValueError as exc:st.error(str(exc))
    if save or submit:
        try:
            options=dict(angle_enabled=angle_enabled,selection_mode=mode,automatic_multiple=multiple,
                automatic_top_n=int(top_n),thumbnail_reference_enabled=visual,central_angle=central,visual_identity=identity,
                weights=weights,vision_model=vision_model,max_image_mb=int(max_mb),on_failure=policy)
            if save:
                repo.save_director_profile(channel_id,options)
                st.success('Preferências salvas somente para este canal.')
            if submit:
                request=Request(title=title,reference_script=pasted if source_mode=='Colar texto' else reference_text(script_file),
                    thumbnails=images.upload([f.getvalue() for f in uploaded or []],max_mb=int(max_mb)),**options)
                snapshot=editorial.prepare(profile)
                batch,created=repo.create_director_batch(request,snapshot,new_version=new_version)
                st.success('Lote de análise adicionado ao AUTOPILOT.' if created else 'Este lote já existe; nenhuma análise duplicada foi criada.')
                if not repo.enabled():st.info('Ative o AUTOPILOT para executar a pesquisa e a análise.')
        except (ValueError,OSError) as exc:st.error(str(exc))


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
        st.info('Seleção automática: '+', '.join(result['recommended_ids'][:request.automatic_top_n])+' · será enfileirada pelo AUTOPILOT ativo.')


@st.fragment(run_every=3)
def _batches(repo,autostart=True):
    for batch in repo.director_batches(limit=10):
        request=Request.model_validate_json(batch['request'])
        with st.expander(request.title+' · '+LABELS.get(batch['state'],batch['state']),key='director_batch_'+batch['batch_id']):
            st.caption('Lote '+batch['batch_id']+' · '+json.loads(batch['snapshot'])['channel']['name'])
            if batch['error']:st.warning(batch['error'])
            if batch['analysis']:
                result=json.loads(batch['analysis'])
                st.download_button('Exportar análise e IDs (.json)',json.dumps({'batch':batch,'analysis':result},ensure_ascii=False,indent=2),
                    file_name='historical-analysis-'+batch['batch_id']+'.json',mime='application/json',key='director_analysis_download_'+batch['batch_id'])
                if batch['state']=='selection':_select(repo,batch,result)
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


def _item(repo,item,batch):
    st.write(('**Análise**' if item['role']=='analysis' else f"**{item['position']}. {item['title']}**")+' · '+LABELS.get(item['state'],item['state']))
    stages=repo.stages(item['task_id'])
    current=next((s['name'] for s in stages.values() if s['state']=='running'),None)
    if current:st.caption('Etapa: '+current+' · '+str(int(time.time()-item['created']))+' s desde o envio')
    if item['error']:st.warning(item['error'])
    if item['role']=='production' and item['state']=='completed' and item['result']:
        result=json.loads(item['result'])
        st.caption('Entregáveis: '+result['deliverables']['directory'])
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
