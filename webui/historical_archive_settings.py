"""Global automatic archive settings and audit results. Rendering never calls an API."""
import io
import json
from pathlib import Path
import streamlit as st
from PIL import Image
from app.models.schema import VideoParams
from app.services.historical_archive import HistoricalArchiveService,ArchiveError
from app.services.historical_archive import settings
from app.services.historical_archive.downloader import local
from app.services.historical_archive.network import safe_url
from app.utils.atomic_files import write_bytes_atomic


def render(set_config):
    cfg=settings.load()
    def save(name,value):set_config('app',settings.PREFIX+name,value)
    with st.expander('Historical Archive Finder · '+('Ativado' if st.session_state.get('haf_enabled',cfg.enabled) else 'Desativado'),expanded=False):
        active=st.toggle('Ativar pesquisa em arquivos históricos',value=cfg.enabled,key='haf_enabled')
        save('enabled',active)
        st.caption('Search historical photographs, documents, maps and archival footage for your video scenes.')
        st.info('Ativado — pesquisa por cena' if active else 'Desativado — nenhuma consulta aos acervos')
        for name,label in [('loc','Library of Congress'),('nara','National Archives (NARA)'),('wikimedia','Wikimedia Commons')]:
            value=st.checkbox(label,value=getattr(cfg,name+'_enabled'),key='haf_'+name,disabled=not active)
            save(name+'_enabled',value)
        st.checkbox('Europeana — fase pendente',value=False,disabled=True,key='haf_europeana_pending')
        st.checkbox('Internet Archive — fase pendente',value=False,disabled=True,key='haf_ia_pending')
        modes={'historical_plus_stock':'Automático: acervos → bancos → IA habilitada',
               'historical_research_only':'Somente pesquisa (sem inserir no vídeo)'}
        mode=st.selectbox('Modo de pesquisa histórica',list(modes),index=list(modes).index(cfg.mode),format_func=modes.get,key='haf_mode',disabled=not active)
        save('mode',mode)
        for name,label in [('photographs','Fotografias históricas'),('documents','Documentos e registros desclassificados'),('maps','Mapas e diagramas'),('footage','Filmagens de arquivo'),('auto_download_rights_cleared','Baixar automaticamente somente itens com direitos liberados'),('preserve_aspect','Preservar a proporção original'),('show_credits','Mostrar relatório de fontes e créditos'),('llm_queries','Usar modelo central para elaborar consultas em inglês (pode ter custo)')]:
            value=st.checkbox(label,value=getattr(cfg,name),key='haf_'+name,disabled=not active)
            save(name,value)
        st.caption('Automático: itens incertos/restritos são ignorados. Sem material histórico, continua nos bancos e na IA habilitada, respeitando o limite de imagens.')
        st.caption('Nenhuma aprovação manual é solicitada. Os créditos de materiais utilizados são preservados no manifesto.')
        for name,label,minimum,maximum in [('candidates_per_scene','Candidatos por cena',1,20),('max_downloads_per_video','Máximo de downloads históricos por vídeo',1,300),('max_file_mb','Tamanho máximo por arquivo (MB)',1,500)]:
            value=st.number_input(label,min_value=minimum,max_value=maximum,value=getattr(cfg,name),step=1,key='haf_'+name,disabled=not active)
            save(name,value)
        for name,label in [('request_timeout_seconds','Timeout das consultas (s)'),('request_interval_seconds','Intervalo mínimo entre pedidos por fonte (s)'),('cache_ttl_hours','Validade do cache (horas)')]:
            low,high=(2.,60.) if name=='request_timeout_seconds' else (.2,60.) if name=='request_interval_seconds' else (0.,720.)
            save(name,st.number_input(label,min_value=low,max_value=high,value=float(getattr(cfg,name)),key='haf_'+name,disabled=not active))
        for name,label in [('loc','LOC'),('nara','NARA'),('wikimedia','Commons')]:
            save(name+'_interval_seconds',st.number_input('Intervalo mínimo '+label+' (s)',min_value=.2,max_value=60.,value=float(getattr(cfg,name+'_interval_seconds')),key='haf_interval_'+name,disabled=not active))
        save('nara_monthly_limit',st.number_input('Teto mensal local de pedidos NARA',min_value=1,max_value=100000,value=cfg.nara_monthly_limit,key='haf_nara_monthly',disabled=not active))
        save('user_agent',st.text_input('Identificação da aplicação / contato (User-Agent)',value=cfg.user_agent,key='haf_user_agent',disabled=not active))
        save('min_score',st.slider('Pontuação editorial mínima para inserção automática',0.,100.,float(cfg.min_score),key='haf_score',disabled=not active))
        save('language',st.selectbox('Idioma preferido de consulta',['en','pt','es','fr','de'],index=['en','pt','es','fr','de'].index(cfg.language) if cfg.language in ['en','pt','es','fr','de'] else 0,key='haf_language',disabled=not active))
        save('preferred_period',st.text_input('Período preferido (opcional)',value=cfg.preferred_period,key='haf_period',disabled=not active))
        current=settings.mapping()
        key=st.text_input('Chave da API NARA (opcional para usar as outras fontes)',value=str(current.get('historical_archive_nara_api_key') or ''),type='password',key='haf_nara_key',disabled=not active)
        save('nara_api_key',key.strip())
        st.caption('NARA também aceita NARA_API_KEY. A API v2 exige chave própria. LOC e Commons não exigem chave. Consultas ao modelo central só ocorrem com a opção acima marcada.')
        if st.button('Verificar fontes selecionadas',key='haf_check',disabled=not active):
            st.session_state.haf_health=HistoricalArchiveService('source-check').health_check()
        if st.session_state.get('haf_health'):st.json(st.session_state.haf_health)
        st.button('Salvar configurações históricas',key='haf_save')
        st.caption('Configurações são persistidas pelo MPT. Desligar impede novas consultas/downloads, sem apagar arquivos anteriores.')
        st.markdown('**Resultados e fontes por projeto**')
        task_id=st.text_input('ID do projeto para consultar a pesquisa histórica',key='haf_task_id').strip()
        if not task_id:return
        try:
            service=HistoricalArchiveService(task_id)
            folder=service.folder
            task_dir=folder.parent
            if '/chapters/' in task_id:task_dir=task_dir/'chapters'/task_id.rsplit('/',1)[-1]
            if not task_dir.exists():
                st.info('Projeto não encontrado. Use o ID de uma tarefa já salva.')
                return
            if st.button('Pesquisar cenas do projeto',key='haf_research',disabled=not active):
                saved=json.loads((task_dir/'script.json').read_text(encoding='utf-8'))
                plan_file=task_dir/'mixed-scenes.json'
                if plan_file.exists():scenes=json.loads(plan_file.read_text())['scenes']
                else:
                    import re
                    scenes=[{'id':i+1,'text':text} for i,text in enumerate(re.split(r'(?<=[.!?])\s+|\n+',saved['script'])) if text.strip()][:180]
                from app.services.historical_archive import research
                research.submit(task_id,scenes,saved.get('search_terms'))
            from app.services.historical_archive import research
            if research.status(task_id):st.info(research.status(task_id))
            st.button('Atualizar resultados históricos',key='haf_refresh')
            if st.button('Cancelar pesquisa deste projeto',key='haf_cancel'):
                research.cancel(task_id)
                st.rerun()
            data=service.snapshot()
            for provider,status in data['providers'].items():
                st.caption(provider+': '+status.get('status','')+' '+status.get('error',''))
            if not data['scenes']:
                st.info('Ainda não há candidatos salvos para este projeto.')
            else:
                scene_key=st.selectbox('Cena da pesquisa histórica',list(data['scenes']),key='haf_review_scene')
                scene=data['scenes'][scene_key]
                st.write(scene['text'])
                for item in scene.get('candidates',[]):
                    candidate=item['candidate']
                    prefix='haf_'+scene_key+'_'+item['id']
                    review_service=service
                    if scene_key.startswith('chapter_'):
                        chapter=scene_key.split('_')[1]
                        review_service=HistoricalArchiveService(task_id.split('/')[0]+'/chapters/'+chapter)
                    with st.expander(candidate['title']+' · '+item['state'],expanded=False):
                        st.write({'Instituição':candidate['institution'],'Data':candidate['date_created'],'Tipo':candidate['media_type'],
                                  'Direitos':candidate['rights_statement'],'Licença':candidate['license_url'],'Crédito':candidate['attribution'],
                                  'Pontuação':item['score'],'Motivo':item['rights_reason'],'Classificação':item['score_explanation']})
                        try:st.link_button('Abrir fonte',safe_url(candidate['source_url']))
                        except ValueError:st.caption('URL da fonte não validada; revise o registro original.')
                        if item.get('downloaded_file'):
                            path=local(folder,item['downloaded_file'])
                            if path.is_file() and path.suffix=='.png':st.image(str(path))
                        elif candidate.get('thumbnail_url') and st.button('Carregar prévia do registro',key=prefix+'_preview',disabled=not active):
                            raw=review_service.transport().get(candidate['provider'],safe_url(candidate['thumbnail_url']),max_bytes=3*1024*1024)
                            with Image.open(io.BytesIO(raw)) as image:
                                image.thumbnail((800,800));st.image(image.copy())
                        allowed=item['rights_status']=='rights_cleared'
                        if st.button('Baixar arquivo liberado',key=prefix+'_download',disabled=not active or not allowed or mode=='historical_research_only'):
                            path,_=review_service.download_item(scene['scene_id'],item['id'])
                            if path:st.success('Arquivo liberado validado e associado à cena. A geração usa os arquivos automaticamente.')
                            else:st.warning('Arquivo não baixado; confira os direitos, limites e erros no manifesto.')
                            st.rerun()
            if cfg.show_credits:
                for name in ('sources_and_credits.md','sources_and_credits.json','manifest.json','search_log.json'):
                    path=folder/name
                    if path.is_file():st.download_button('Baixar '+name,data=path.read_bytes(),file_name=name,key='haf_export_'+name)
            context=task_dir/'historical-archive-resume.json'
            if context.exists() and st.button('Continuar projeto histórico sem refazer áudio',key='haf_resume'):
                from app.services.historical_archive.pipeline import load_resume
                from app.services import webui_task
                project=load_resume(task_id)
                webui_task.submit_generation(task_id,project['params'],capture_logs=True)
                st.success('Retomada iniciada com o áudio e as legendas salvos. Acompanhe no gerenciador de tarefas.')
        except (ValueError,OSError,KeyError) as exc:
            st.warning(str(exc))
