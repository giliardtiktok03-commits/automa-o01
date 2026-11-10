"""Story Intelligence controls embedded in the existing Skills block."""
import json
import streamlit as st
from app.config import config
from app.models.story_intelligence import EpisodeBlueprint
from app.services import story_intelligence as story


def render(params):
    if not params.skills_enabled or story.SKILL_ID not in params.skill_ids:
        return
    with st.expander('Beyond the Archives · Story Intelligence', expanded=True):
        st.caption('Direção editorial pelo GPT via OpenAI. Memória, duplicatas e validação permanecem locais. Analisar não inicia roteiro, áudio, imagens ou vídeo.')
        settings = config.snapshot_config_with_pending(config.app)
        settings['_channel_skill_snapshot'] = [item.model_dump() for item in params.skill_snapshot]
        status = story.model_status(settings)
        topic = st.text_input('Topic or Working Title', key='bta_topic')
        angle_text = st.text_input('Ângulo distinto ou pergunta específica (opcional)', key='bta_distinct_angle')
        duration = st.number_input('Duração alvo (minutos)', min_value=1, max_value=180, value=20, key='bta_duration')
        mode = st.selectbox('Modo da análise editorial', ['Automático · GPT pela OpenAI', 'Análise local simplificada'], key='bta_analysis_mode_v2')
        use_model = None if mode.startswith('Automático') else False
        if use_model is False:
            st.info('Análise local simplificada selecionada: usa regras iniciais, sem avaliação editorial pelo GPT.')
        elif status['configured']:
            st.caption('GPT configurado: ' + status['model'] + ' · OpenAI. Uma solicitação de texto por análise; pode haver custo.')
        else:
            st.info('OpenAI não configurada: será usada análise local simplificada. Configure a chave e o modelo em Configurar modelo de IA para a direção editorial GPT.')
        source_text = st.text_area('Fontes e trechos fornecidos — JSON (opcional)', value='[]', height=100, key='bta_sources', help='Lista com id, title, url, excerpt e interpretation (documented, disputed, hypothesis ou unknown). URLs não são acessadas automaticamente.')
        def store_result(bp):
            st.session_state['bta_blueprint'] = bp.model_dump()
            st.session_state.pop('bta_approved', None)
            st.session_state.pop('bta_episode_id', None)
            st.session_state.pop('bta_model_failure', None)
            st.session_state['bta_revision_key'] = st.session_state.get('bta_revision_key', 0) + 1

        if st.button('Analyze Story · Analisar tema', key='bta_analyze', disabled=not topic.strip()):
            st.session_state.pop('bta_approved', None)
            st.session_state.pop('bta_blueprint', None)
            st.session_state.pop('bta_model_failure', None)
            try:
                request = dict(topic=topic, duration=int(duration), sources=json.loads(source_text), distinct_angle=angle_text)
                try:
                    with st.spinner('GPT preparando Narrative Blueprint…' if use_model is not False and status['configured'] else 'Preparando análise local simplificada…'):
                        bp = story.analyze(**request, use_model=use_model, app_config=settings)
                    store_result(bp)
                except story.StoryModelUnavailable as exc:
                    st.session_state['bta_model_failure'] = {'reason': exc.reason, 'request': request}
            except (ValueError, TypeError, OSError) as exc:
                st.error(str(exc))
        failed = st.session_state.get('bta_model_failure')
        if failed:
            st.warning('A análise GPT não foi concluída (' + failed['reason'] + '). Nenhum roteiro ou vídeo foi iniciado. Você pode tentar a API novamente ou usar a análise simplificada abaixo.')
            if st.button('Executar análise local simplificada', key='bta_local_fallback'):
                try:
                    store_result(story.analyze(**failed['request'], use_model=False, fallback_reason=failed['reason'], app_config=settings))
                except (ValueError, TypeError, OSError) as exc:
                    st.error(str(exc))
        tabs = st.tabs(['Channel Memory', 'Narrative Strategy', 'Research & Evidence', 'Narrative Blueprint'])
        with tabs[0]:
            inventory = story.memory()
            st.dataframe([{'ID': r['id'], 'Título': r['title'], 'Status': r['status']} for r in inventory['videos']], hide_index=True)
            st.caption('Datas, URLs, métricas e estruturas reais dos vídeos não foram fornecidas. Os arquétipos iniciais são hipóteses baseadas nos títulos.')
            with st.expander('Editar memória do canal'):
                memory_text = st.text_area('Inventário JSON', value=json.dumps(inventory, ensure_ascii=False, indent=2), height=180, key='bta_memory_editor')
                confirm_published = st.checkbox('Confirmo alterações explícitas de status publicado/agendado', key='bta_confirm_publication')
                if st.button('Salvar memória editorial', key='bta_save_memory'):
                    try:
                        value = json.loads(memory_text)
                        before = {r['id']: r for r in inventory['videos']}
                        changed = any(r.get('status') in {'published', 'scheduled'} and before.get(r.get('id'), {}).get('status') != r.get('status') for r in value.get('videos', []))
                        if changed and not confirm_published:
                            raise story.StoryError('Confirme a alteração de status publicado/agendado.')
                        story.save_memory(value)
                        st.session_state.pop('bta_approved', None)
                        st.success('Memória salva. Revise aprovações anteriores antes de gerar novos roteiros.')
                        st.rerun()
                    except (ValueError, TypeError, AttributeError) as exc:
                        st.error(str(exc))
        data = st.session_state.get('bta_blueprint')
        with tabs[3]:
            saved = story.saved_blueprints()
            if saved:
                selected = st.selectbox('Blueprint salvo', saved, key='bta_saved')
                if st.button('Carregar blueprint', key='bta_load'):
                    bp = story.load_blueprint(selected)
                    st.session_state['bta_blueprint'] = bp.model_dump()
                    st.session_state['bta_episode_id'] = selected
                    st.session_state.pop('bta_approved', None)
                    st.session_state['bta_revision_key'] = st.session_state.get('bta_revision_key', 0) + 1
                    st.rerun()
        if not data:
            st.info('Informe um tema e clique em Analyze Story para começar.')
            return
        bp = EpisodeBlueprint.model_validate(data)
        if bp.analysis_method == 'central_model':
            st.success('Narrative Blueprint · GPT / OpenAI · ' + (bp.analysis_model or 'modelo não registrado no plano antigo'))
        elif bp.fallback_reason == 'duplicate_blocked':
            st.warning('Duplicata detectada localmente. O GPT não foi chamado para esta proposta.')
        else:
            st.warning('ANÁLISE LOCAL SIMPLIFICADA — sem direção editorial GPT. Motivo: ' + (bp.fallback_reason or 'plano local anterior'))
        with tabs[0]:
            st.info(bp.editorial_memory_check.status + ': ' + bp.editorial_memory_check.explanation)
            st.write('Episódios relacionados: ' + ', '.join(bp.editorial_memory_check.matched_video_ids))
        with tabs[1]:
            st.write('Potencial narrativo: ' + (bp.narrative_potential or 'Não avaliado no plano antigo.'))
            st.write('Motor dominante: **' + bp.primary_story_engine + '**')
            st.write(bp.reason_for_structure)
            st.write(bp.alternative_engines_note)
            st.write('Pergunta central: ' + bp.core_question)
            st.write('Promessa: ' + bp.title_promise)
            st.write('Abertura: ' + bp.opening_hook_strategy)
            st.write('Progressão: ' + bp.progression_strategy)
            st.write('Desfecho: ' + bp.ending_strategy)
            st.write('Ritmo: ' + bp.pacing_strategy)
            for conflict in bp.central_conflicts:
                st.write('Conflito: ' + conflict.tension)
                st.caption('Consequências: ' + conflict.stakes + ' · Ressalva: ' + conflict.uncertainty)
            st.caption('Revise motor, pergunta e beats no JSON da aba Episode Blueprint.')
        with tabs[2]:
            st.write('Fontes fornecidas: ' + str(len(bp.source_register)))
            st.json([row.model_dump() for row in bp.source_register])
            if bp.claim_register:
                labels = {'documented_fact': 'Fato documentado (suporte citado; revisão pendente)', 'allegation': 'Alegação atribuída', 'inference': 'Inferência', 'research_gap': 'Lacuna de pesquisa'}
                st.dataframe([{'Classificação': labels[row.classification], 'Afirmação': row.statement, 'Fontes': ', '.join(row.source_ids), 'Ressalva': row.caveat, 'Central': row.material} for row in bp.claim_register], hide_index=True)
            for text in bp.research_questions + bp.risk_flags + bp.revision_notes:
                st.write('• ' + text)
            st.warning('O módulo não busca nem autentica fontes. Revisão humana confirma se os trechos sustentam as afirmações e se há versões conflitantes.')
        with tabs[3]:
            st.write('Estado: **' + bp.readiness + '**')
            revision_key = str(st.session_state.get('bta_revision_key', 0))
            revised = st.text_area('Blueprint revisável — JSON', value=bp.model_dump_json(indent=2), height=340, key='bta_json_'+revision_key)
            reviewed = st.checkbox('Revisei fontes, suporte dos beats, promessa, causalidade, conclusão e ressalvas', key='bta_evidence_reviewed')
            angle = st.checkbox('Confirmei um evento e uma pergunta distintos dos episódios semelhantes', key='bta_angle_reviewed')
            if st.button('Validar revisão editorial', key='bta_review'):
                try:
                    checked = story.review(json.loads(revised), evidence_reviewed=reviewed, distinct_angle_reviewed=angle)
                    st.session_state['bta_blueprint'] = checked.model_dump()
                    st.session_state.pop('bta_approved', None)
                    st.session_state['bta_revision_key'] = int(revision_key) + 1
                    st.rerun()
                except (ValueError, TypeError) as exc:
                    st.error(str(exc))
            if st.button('Approve for Script · Aprovar para roteiro', key='bta_approve', disabled=bp.readiness != 'ready_to_write' or not reviewed):
                try:
                    # Always validate edited JSON again, never trust client readiness flags.
                    approved = story.approve(json.loads(revised), evidence_reviewed=reviewed, distinct_angle_reviewed=angle)
                    st.session_state['bta_approved'] = approved.model_dump()
                    st.session_state['bta_blueprint'] = approved.model_dump()
                    st.success('Blueprint aprovado. Use exatamente o tema de entrada no campo Tema do vídeo.')
                except (ValueError, TypeError) as exc:
                    st.error(str(exc))
            status = st.selectbox('Status ao salvar na biblioteca', ['Somente blueprint', 'planned', 'in_production'], key='bta_save_status')
            if st.button('Save to Editorial Library · Salvar blueprint', key='bta_save'):
                try:
                    # Edits are preserved, but editing cannot grant approval by itself.
                    checked = story.review(json.loads(revised), evidence_reviewed=reviewed, distinct_angle_reviewed=angle)
                    episode_id = story.save_blueprint(checked, episode_id=st.session_state.get('bta_episode_id'), status=None if status == 'Somente blueprint' else status)
                    st.session_state['bta_episode_id'] = episode_id
                    st.session_state.pop('bta_approved', None)
                    st.success('Revisão salva: '+episode_id+'. Nenhuma publicação foi marcada automaticamente.')
                except (ValueError, TypeError) as exc:
                    st.error(str(exc))
            st.download_button('Exportar Episode Blueprint JSON', bp.model_dump_json(indent=2), 'episode-blueprint.json', 'application/json', key='bta_export_json')
            st.download_button('Exportar relatório editorial', story.report(bp), 'episode-blueprint.md', 'text/markdown', key='bta_export_md')
