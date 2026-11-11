"""Channel skills controls; installing instructions does not activate them."""

import streamlit as st

from app.config import config
from app.services import channel_skills as library
from app.services import channel_skill_runtime as runtime


TEMPLATE = '''---
name: Minha skill editorial
version: "1.0"
---
# Público e propósito
Preencha as decisões aprovadas para o canal.

# Regras de roteiro
Defina idioma, estrutura, abertura e profundidade.

# Tema e ângulo por vídeo
Explique como propor um recorte original sem inventar fatos.

# Direção visual e musical
Defina as orientações editoriais desejadas.
'''


def render(panel, params, set_config, heading):
    settings = config.snapshot_config_with_pending(config.ui)
    if "channel_skills_pending_ids" in st.session_state:
        st.session_state["channel_skill_ids"] = st.session_state.pop("channel_skills_pending_ids")
    with panel:
        with st.container(border=True, key="stage_channel_skills"):
            heading(0, "Configurações de Skills", "#be123c")
            from app.services import story_intelligence
            story_intelligence.install()
            from app.services.historical_director.library import install as install_director
            install_director()
            installed = library.installed()
            names = {item.skill_id: item.name for item in installed}
            params.skills_enabled = st.checkbox(
                "Ativar Skills editoriais", value=bool(settings.get("skills_enabled", False)), key="channel_skills_enabled")
            saved = st.session_state.get("channel_skill_ids", settings.get("skill_ids", []))
            missing = [item for item in saved if item not in names]
            if missing:
                st.warning("Algumas skills salvas não estão mais instaladas. Os projetos anteriores mantêm suas cópias.")
                st.session_state["channel_skill_ids"] = [item for item in saved if item in names]
            selected = st.multiselect(
                "Skills ativas — a primeira tem prioridade", list(names),
                default=[item for item in saved if item in names], format_func=lambda value: names[value],
                key="channel_skill_ids", max_selections=8, disabled=not params.skills_enabled,
            )
            params.skill_ids = list(selected)
            try:
                runtime.freeze(params)
            except library.ChannelSkillError as exc:
                st.error(str(exc))
                st.stop()
            st.session_state["active_channel_skill_snapshot"] = [item.model_dump() for item in params.skill_snapshot]
            set_config("ui", "skills_enabled", bool(st.session_state["channel_skills_enabled"]))
            set_config("ui", "skill_ids", list(selected))
            if params.skill_snapshot:
                st.caption("Prioridade: " + " → ".join(item.name for item in params.skill_snapshot))
                st.caption("As instruções e seus hashes serão salvos no projeto. Alterações posteriores na biblioteca não mudam trabalhos já enviados.")
                voice_profile = runtime.metadata_value(params, "voice_profile", 600)
                if voice_profile:
                    st.info("Perfil vocal sugerido: " + voice_profile)
                    st.caption("A voz selecionada nas configurações de áudio será mantida. A skill não troca a voz automaticamente.")
            else:
                st.caption("Nenhuma skill ativa: o MPT usa o modo padrão. O perfil editorial do seu canal ainda pode ser definido antes de instalar uma skill.")
            st.caption("Configurações explícitas do projeto prevalecem. Skills complementares não substituem a primeira em caso de conflito.")

            from webui.story_intelligence import render as render_story_intelligence
            render_story_intelligence(params)
            approved = st.session_state.get("bta_approved")
            if approved and params.skills_enabled and story_intelligence.SKILL_ID in params.skill_ids:
                try:
                    # Subject widget is rendered later in Main.py; read its current state.
                    params.video_subject = st.session_state.get("video_subject", params.video_subject)
                    story_intelligence.bind(params, approved)
                except ValueError as exc:
                    st.caption(str(exc))
            st.session_state["active_channel_skill_snapshot"] = [item.model_dump() for item in params.skill_snapshot]

            with st.expander("Instalar ou gerenciar SKILL.md", expanded=False):
                uploaded = st.file_uploader("Carregar arquivo SKILL.md (UTF-8, até 24 KB)", type=["md"], key="channel_skill_upload")
                skill_id = st.text_input("Identificador da nova skill", placeholder="meu-canal", key="channel_skill_new_id")
                if st.button("Instalar skill", key="channel_skill_install", disabled=uploaded is None):
                    try:
                        library.save(skill_id.strip(), uploaded.getvalue())
                        st.rerun()
                    except library.ChannelSkillError as exc:
                        st.error(str(exc))
                st.download_button("Baixar modelo vazio de SKILL.md", TEMPLATE.encode("utf-8"), "SKILL.md", "text/markdown", key="channel_skill_template")
                st.caption("O modelo precisa ser preenchido com regras aprovadas. Nenhuma identidade de canal é ativada automaticamente. Não inclua chaves ou senhas.")
                if installed:
                    editing = st.selectbox("Skill para visualizar ou editar", list(names), index=list(names).index(selected[0]) if selected else 0, format_func=lambda value: names[value], key="channel_skill_edit_id")
                    current = library.load(editing)
                    st.caption(f"Versão: {current.version or 'sem rótulo'} · SHA-256: {current.sha256[:12]}")
                    content = st.text_area("Conteúdo de SKILL.md", value=current.content, height=220, key=f"channel_skill_editor_{editing}_{current.sha256}")
                    if st.button("Salvar nova revisão", key="channel_skill_save"):
                        try:
                            library.save(editing, content.encode("utf-8"), replace=True)
                            st.rerun()
                        except library.ChannelSkillError as exc:
                            st.error(str(exc))
                    st.download_button("Exportar skill selecionada", current.content.encode("utf-8"), "SKILL.md", "text/markdown", key="channel_skill_export")
                    if st.button("Arquivar skill da biblioteca", key="channel_skill_archive"):
                        library.remove(editing)
                        st.session_state["channel_skills_pending_ids"] = [value for value in selected if value != editing]
                        st.rerun()
