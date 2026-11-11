"""First Autopilot panel: saved channels and recovery queue, no new publishing."""
import streamlit as st

from app.models.autopilot import ChannelProfile
from app.services.autopilot.repository import Repository, Conflict
from app.services.autopilot import recovery, worker

STATES = {"queued": "Na fila", "running": "Recuperando", "waiting_remote": "Aguardando provedor/projeto",
          "completed": "Vídeo recuperado", "blocked": "Requer revisão", "failed": "Falha", "cancelled": "Cancelado"}


def render(params=None, *, repository=None, autostart=True):
    repository = repository or Repository()
    if autostart and repository.enabled():
        worker.ensure_started()
    with st.expander("AUTOPILOT · Canais e recuperação automática"):
        st.caption("Primeira entrega: cadastro de canais e retomada de projetos mistos salvos. Pesquisa, criação a partir de título e publicação automática serão conectadas nas próximas entregas.")
        channels = repository.channels()
        options = ["__new__", *[c["channel_id"] for c in channels]]
        pending = st.session_state.pop("autopilot_pending_channel", None)
        if pending in options:
            st.session_state["autopilot_channel_edit"] = pending
        selected = st.selectbox("Configurar canal", options, format_func=lambda x: "Novo canal" if x == "__new__" else next(c["name"] for c in channels if c["channel_id"] == x), key="autopilot_channel_edit")
        old = next((c for c in channels if c["channel_id"] == selected), None)
        defaults = old or {"channel_id": "", "name": "", "language": "pt-BR", "niche": "", "skill_ids": [], "deepinfra_unlimited": True, "image_limit": 120, "auto_resume": False}
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
            save = st.form_submit_button("Salvar canal")
        if save:
            try:
                profile = ChannelProfile(channel_id=identifier, name=name, language=language, niche=niche,
                                         skill_ids=defaults["skill_ids"], deepinfra_unlimited=unlimited, image_limit=int(limit), auto_resume=auto)
                repository.save_channel(profile, expected_version=old["version"] if old else 0)
                st.session_state["autopilot_pending_channel"] = identifier
                st.success("Canal salvo. Projetos já vinculados mantêm a configuração registrada no vínculo.")
                st.rerun()
            except (ValueError, Conflict) as exc:
                st.error(str(exc))
        enabled = st.checkbox("Ativar recuperação automática", value=repository.enabled(), key="autopilot_worker_enabled")
        if enabled != repository.enabled():
            repository.set_enabled(enabled)
            if enabled and autostart:
                worker.ensure_started()
        st.caption("Ao reabrir o MPT, a fila continua do disco. Desativar impede o próximo projeto; a operação em andamento termina em segurança. Nenhum vídeo é publicado por esta entrega.")
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
        _render_jobs(repository)


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
