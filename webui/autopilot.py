"""Saved channels, frozen Skills, editorial jobs and recovery queue."""
import json
import streamlit as st

from app.models.autopilot import ChannelProfile
from app.services.autopilot.repository import Repository, Conflict
from app.services.autopilot import recovery, worker
from app.models.llm_provider import LLM_PROVIDER_REGISTRY
from app.services.historical_director.library import SKILL_ID

STATES = {"queued": "Na fila", "running": "Recuperando", "waiting_remote": "Aguardando provedor/projeto",
          "completed": "Vídeo recuperado", "blocked": "Requer revisão", "failed": "Falha", "cancelled": "Cancelado"}


def render(params=None, *, repository=None, autostart=True, worker_control=True):
    repository = repository or Repository()
    if autostart and repository.enabled():
        worker.ensure_started()
    with st.expander("AUTOPILOT · Canais e recuperação automática"):
        st.caption("Título e canal → pesquisa com fontes, roteiro com Skills e pacote editorial. A recuperação de projetos antigos continua disponível. Narração, renderização e publicação deste novo fluxo serão conectadas depois.")
        channels = repository.channels()
        options = ["__new__", *[c["channel_id"] for c in channels]]
        pending = st.session_state.pop("autopilot_pending_channel", None)
        if pending in options:
            st.session_state["autopilot_channel_edit"] = pending
        selected = st.selectbox("Configurar canal", options, format_func=lambda x: "Novo canal" if x == "__new__" else next(c["name"] for c in channels if c["channel_id"] == x), key="autopilot_channel_edit")
        old = next((c for c in channels if c["channel_id"] == selected), None)
        defaults = {**ChannelProfile(channel_id="new", name="Novo canal").model_dump(), **(old or {"channel_id": "", "name": "", "language": "pt-BR", "niche": "", "skill_ids": [], "deepinfra_unlimited": True, "image_limit": 120, "auto_resume": False})}
        director_selected = bool(params is not None and params.skills_enabled and SKILL_ID in params.skill_ids)
        panel_ids = list(params.skill_ids) if params is not None and params.skills_enabled else []
        if selected == "__new__" and director_selected:
            st.info("Cadastre o canal da Historical Documentary Director no bloco 00 · Configurações de Skills.")
        elif old and SKILL_ID in old['skill_ids']:
            st.info('O perfil, as Skills e a autorização de pesquisa deste canal estão no bloco 00 · Configurações de Skills.')
            _recovery_channel_options(repository, old)
        else:
            with st.form("autopilot_channel_form_" + selected):
                identifier = st.text_input("Identificador do canal (letras minúsculas, números, hífen)", value=defaults["channel_id"], disabled=old is not None)
                name = st.text_input("Nome do canal", value=defaults["name"])
                language = st.text_input("Idioma", value=defaults["language"])
                niche = st.text_input("Nicho", value=defaults["niche"])
                st.caption("Na recuperação, roteiro, voz, legendas e Skills originais do projeto são preservados. Idioma/nicho do cadastro não reescrevem um vídeo já iniciado.")
                unlimited = st.checkbox("DeepInfra sem limite de quantidade na recuperação", value=defaults["deepinfra_unlimited"])
                limit = st.number_input("Limite total quando o provedor não estiver sem limite", min_value=0, max_value=120, value=defaults["image_limit"])
                auto = st.checkbox("Autorizar recuperação automática dos projetos vinculados a este canal", value=defaults["auto_resume"])
                st.caption("Novas imagens podem consumir saldo. O provedor salvo no projeto é preservado; esta opção não troca outros geradores para DeepInfra.")
                st.markdown("**Pesquisa e roteiro de novos vídeos**")
                if director_selected:
                    sync_skills = False
                    st.caption('O vínculo de Skills é gerenciado no bloco 00; este formulário preserva a seleção já salva no canal.')
                else:
                    sync_skills = st.checkbox("Salvar neste canal a seleção do painel 00 · Configurações de Skills",
                                              value=bool(panel_ids) and not defaults["skill_ids"], disabled=params is None,
                                              key="autopilot_sync_skills_" + selected)
                    st.caption("Painel 00: " + (" → ".join(panel_ids) if panel_ids else "nenhuma Skill ativa"))
                    st.caption("Skills salvas no canal: " + (" → ".join(defaults["skill_ids"]) if defaults["skill_ids"] else "padrão do MPT"))
                minutes = st.number_input("Duração desejada (minutos)", min_value=3, max_value=30, value=defaults["target_minutes"])
                backend = st.selectbox('Modo de pesquisa', ['openai','public_login'], index=['openai','public_login'].index(defaults['research_backend']),
                    format_func=lambda x:'API OpenAI com busca web' if x=='openai' else 'Pesquisa pública + ChatGPT/Codex por login')
                research_model = st.text_input("Modelo OpenAI para pesquisa e Blueprint", value=defaults["research_model"])
                domains = st.text_area("Restringir pesquisa a estes domínios (opcional, um por linha)", value="\n".join(defaults["research_domains"]))
                providers = ["current", *[p.provider_id for p in LLM_PROVIDER_REGISTRY]]
                provider = st.selectbox("Provedor do roteiro", providers, index=providers.index(defaults["script_provider"]) if defaults["script_provider"] in providers else 0,
                                       format_func=lambda x: "Usar provedor atual do MPT" if x == "current" else next(p.default_label for p in LLM_PROVIDER_REGISTRY if p.provider_id == x))
                script_model = st.text_input("Modelo do roteiro (vazio usa o configurado no provedor)", value=defaults["script_model"])
                auto_editorial = st.checkbox("Autorizar pesquisa e roteiro automáticos para este canal", value=defaults["auto_editorial"])
                st.caption("Modo API: pesquisa OpenAI pode consumir saldo. Modo público: descoberta pela Wikipédia, leitura de referências externas e texto pelo provedor ChatGPT/Codex por login, sujeito aos limites da conta. O Blueprint passa por revisão automática. O campo de modelo OpenAI só vale no modo API.")
                save = st.form_submit_button("Salvar canal")
            if save:
                try:
                    profile = ChannelProfile(channel_id=identifier, name=name, language=language, niche=niche,
                                             skill_ids=panel_ids if sync_skills else defaults["skill_ids"], deepinfra_unlimited=unlimited, image_limit=int(limit), auto_resume=auto,
                                             target_minutes=int(minutes), research_backend=backend, research_model=research_model, research_domains=[d.strip() for d in domains.splitlines() if d.strip()],
                                             script_provider=provider, script_model=script_model, auto_editorial=auto_editorial)
                    repository.save_channel(profile, expected_version=old["version"] if old else 0)
                    st.session_state["autopilot_pending_channel"] = identifier
                    st.success("Canal salvo. Projetos já vinculados mantêm a configuração registrada no vínculo.")
                    st.rerun()
                except (ValueError, Conflict) as exc:
                    st.error(str(exc))
        _new_title(repository, channels)
        if worker_control:
            render_worker_control(repository, autostart=autostart)
        else:
            st.caption('A execução compartilhada das filas é controlada no bloco 00 · Configurações de Skills. A recuperação de projetos continua abaixo.')
        if st.button("Localizar projetos salvos", key="autopilot_discover"):
            st.session_state["autopilot_candidates"] = recovery.discover()
            if not st.session_state["autopilot_candidates"]:
                st.info("Nenhum projeto misto simples compatível encontrado. A recuperação de capítulos será adicionada em outra entrega.")
        candidates = st.session_state.get("autopilot_candidates", [])
        if candidates:
            candidate = st.selectbox("Projeto para recuperar", candidates,
                                     format_func=lambda x: f"{x['title']} · {x['registered']}/{x['total']} cenas registradas · {x['task_id'][:8]}", key="autopilot_candidate")
            st.caption("Cenas registradas serão verificadas no disco antes de reutilizar. Arquivos finais existentes serão apenas validados.")
            channel_ids = [c["channel_id"] for c in channels]
            if channel_ids:
                channel_id = st.selectbox("Canal deste projeto", channel_ids, key="autopilot_enroll_channel")
                if st.button("Vincular e colocar na fila", key="autopilot_enroll"):
                    try:
                        current = recovery.inspect(candidate["task_id"], verify_media=True)
                        created = repository.enroll(current["task_id"], channel_id, current["title"], current["editorial_digest"])
                        st.success("Projeto vinculado à fila persistente" if created else "Projeto já registrado; nenhum pedido duplicado foi criado")
                    except ValueError as exc:
                        st.error(str(exc))
            else:
                st.info("Cadastre um canal antes de vincular o projeto.")
        _render_editorial_jobs(repository)
        _render_jobs(repository)


def render_worker_control(repository, *, autostart=True):
    if st.session_state.pop('autopilot_worker_pending_enabled',False):
        st.session_state['autopilot_worker_enabled']=True
    enabled=st.checkbox('Ativar execução automática das filas',value=repository.enabled(),key='autopilot_worker_enabled')
    if enabled!=repository.enabled():repository.set_enabled(enabled)
    if enabled and autostart:worker.ensure_started()
    st.caption('Controle compartilhado das filas autorizadas. Desativar impede o próximo item; a etapa atual termina em segurança. O progresso é salvo para a próxima abertura do MPT.')


def _recovery_channel_options(repository, channel):
    with st.form('autopilot_recovery_channel_'+channel['channel_id']):
        st.caption('Estas opções afetam somente a recuperação de projetos antigos, preservando o perfil da Skill.')
        unlimited=st.checkbox('DeepInfra sem limite de quantidade na recuperação',value=channel['deepinfra_unlimited'])
        limit=st.number_input('Limite total quando o provedor não estiver sem limite',min_value=0,max_value=120,value=channel['image_limit'])
        auto=st.checkbox('Autorizar recuperação automática dos projetos vinculados a este canal',value=channel['auto_resume'])
        if st.form_submit_button('Salvar opções de recuperação'):
            try:
                profile=ChannelProfile.model_validate({**{k:v for k,v in channel.items() if k!='version'},
                    'deepinfra_unlimited':unlimited,'image_limit':int(limit),'auto_resume':auto})
                repository.save_channel(profile,expected_version=channel['version']);st.rerun()
            except ValueError as exc:st.error(str(exc))


@st.fragment(run_every=2)
def _render_jobs(repository):
    jobs = repository.jobs(limit=50)
    if not jobs:
        st.info("Nenhum projeto na fila AUTOPILOT.")
        return
    for job in jobs:
        st.write(f"**{job['title']}** · {job['channel_id']} · {STATES.get(job['state'], job['state'])}")
        if job["error"]:
            st.caption(job["error"])
        if job["state"] == "completed":
            st.caption("Saída final validada; nenhuma publicação foi feita. Abra o resultado pela lista de tarefas do MPT.")
        if job["state"] in {"blocked", "failed"}:
            if st.button("Reenfileirar com as opções atuais do canal", key="autopilot_retry_" + job["task_id"]):
                repository.retry(job["task_id"], refresh_profile=True)
                st.rerun(scope="fragment")


def _new_title(repository, channels):
    channels=[c for c in channels if SKILL_ID not in c["skill_ids"]]
    if not channels:
        return
    st.markdown('**Criar pesquisa e roteiro de um vídeo novo**')
    with st.form('autopilot_new_editorial'):
        title = st.text_input('Título do novo vídeo', max_chars=300, key='autopilot_new_title')
        channel_id = st.selectbox('Canal do novo vídeo', [c['channel_id'] for c in channels],
                                  format_func=lambda x: next(c['name'] for c in channels if c['channel_id'] == x), key='autopilot_new_channel')
        submit = st.form_submit_button('Pesquisar e gerar roteiro')
    if submit:
        try:
            from app.services.autopilot import editorial
            selected = next(c for c in channels if c['channel_id'] == channel_id)
            profile = ChannelProfile.model_validate({k: v for k, v in selected.items() if k != 'version'})
            snapshot = editorial.prepare(profile)
            task_id, created = repository.submit_editorial(title, snapshot)
            st.success('Pesquisa e roteiro enviados para a fila' if created else 'Este título já está na fila ou concluído neste canal; nenhuma tarefa duplicada foi criada')
            if not repository.enabled():
                st.info('Ative a execução automática das filas para processar este pedido.')
        except ValueError as exc:
            st.error(str(exc))


@st.fragment(run_every=3)
def _render_editorial_jobs(repository):
    render_editorial_results(repository)


def render_editorial_results(repository, *, director=False):
    from app.services.autopilot.editorial import STEP_NAMES
    for job in repository.editorial_jobs(limit=100):
        if repository.director_item(job['task_id']):
            continue
        is_director = any(skill['skill_id']==SKILL_ID for skill in json.loads(job['snapshot']).get('skills',[]))
        if is_director != director:
            continue
        label = 'Roteiro pronto' if job['state'] == 'completed' else 'Pesquisa/roteiro: ' + ('Em andamento' if job['state'] == 'running' else STATES.get(job['state'], job['state']))
        st.write(f"**{job['title']}** · {job['channel_id']} · {label}")
        stages = repository.stages(job['task_id'])
        for key, stage in stages.items():
            if stage['state'] == 'running':
                st.caption(STEP_NAMES.get(key, key))
        if job['error']:
            st.warning(job['error'])
        if job['state'] == 'completed' and job['result']:
            result = json.loads(job['result'])
            with st.expander('Roteiro e fontes · ' + job['title'][:60]):
                st.caption(f"{result['word_count']} palavras · revisão automática concluída · ainda sem gerar vídeo ou publicar")
                st.text_area('Roteiro narrado', value=result['script'], height=300, key='autopilot_script_' + job['task_id'])
                for source in result['research']['sources']:
                    st.write(source['title'] + ' — ' + source['url'])
                st.download_button('Baixar roteiro (.txt)', result['script'], file_name=job['channel_id'] + '-roteiro.txt', mime='text/plain', key='autopilot_download_script_' + job['task_id'])
                st.download_button('Baixar pesquisa, descrição, tags e briefing (.json)', json.dumps(result, ensure_ascii=False, indent=2),
                                   file_name=job['channel_id'] + '-editorial.json', mime='application/json', key='autopilot_download_editorial_' + job['task_id'])
        elif job['state'] in {'failed', 'blocked'}:
            acknowledged = st.checkbox('Entendo que repetir uma chamada de IA pode consumir saldo', key='autopilot_retry_cost_' + job['task_id'])
            if st.button('Repetir etapa pendente', disabled=not acknowledged, key='autopilot_retry_editorial_' + job['task_id']):
                repository.retry_editorial(job['task_id'], acknowledge_cost=True)
                st.rerun()
            if st.button('Refazer pesquisa e roteiro com o mesmo contexto salvo', disabled=not acknowledged, key='autopilot_restart_editorial_' + job['task_id']):
                repository.retry_editorial(job['task_id'], restart=True, acknowledge_cost=True)
                st.rerun()
