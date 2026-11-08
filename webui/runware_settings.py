"""Runware configuration; network calls only on explicit user actions."""
import time
from pathlib import Path
from uuid import uuid4

import streamlit as st

from app.models.schema import VideoParams
from app.services import runware_image as runware
from app.utils import utils


def render(settings, set_config):
    def save(config_key, widget_key):
        set_config("app", config_key, st.session_state[widget_key])

    st.markdown("**Runware · Geração de imagens**")
    key = st.text_input("Chave da API Runware", type="password", value=runware.api_key(settings),
                        key="runware_api_key_input", on_change=save,
                        args=("runware_api_key", "runware_api_key_input")).strip()
    set_config("app", "runware_api_key", key)
    st.caption("Crie sua chave em https://my.runware.ai/. Ela fica na configuração local; não vai para os projetos.")
    query = st.text_input("Pesquisar modelos Runware", value="FLUX", key="runware_model_query")
    if st.button("Conectar e consultar modelos (sem gerar imagem)", disabled=not key, key="runware_models"):
        try:
            st.session_state.runware_catalog = runware.Client(key).search(query)
            st.success("Conexão confirmada; nenhuma imagem foi solicitada.")
        except runware.RunwareError as exc:
            st.error(str(exc))
    if st.session_state.get("runware_catalog"):
        st.dataframe(st.session_state.runware_catalog, hide_index=True)
    model = st.text_input("Modelo Runware (identificador AIR)", value=str(settings.get("runware_image_model") or runware.DEFAULT_MODEL),
                          key="runware_model_input", on_change=save, args=("runware_image_model", "runware_model_input")).strip()
    set_config("app", "runware_image_model", model)
    st.caption("Inicial: FLUX.1 Schnell = runware:100@1, com 4 passos. FLUX.1 Dev = runware:101@1, normalmente com 20 passos. Consulte a compatibilidade antes de trocar o modelo.")
    steps = st.number_input("Passos Runware (0 = padrão do modelo)", min_value=0, max_value=100,
                            value=int(settings.get("runware_image_steps", 4)), key="runware_steps_input",
                            on_change=save, args=("runware_image_steps", "runware_steps_input"))
    set_config("app", "runware_image_steps", steps)
    sizes = [1024, 2048]
    size = st.selectbox("Lado maior da imagem Runware", sizes,
                         index=sizes.index(settings.get("runware_image_size", 1024)) if settings.get("runware_image_size", 1024) in sizes else 0,
                         key="runware_size_input", on_change=save, args=("runware_image_size", "runware_size_input"))
    set_config("app", "runware_image_size", size)
    wait = st.number_input("Espera máxima Runware por imagem (minutos)", min_value=1, max_value=120,
                            value=int(settings.get("runware_image_wait_minutes", 10)), key="runware_wait_input",
                            on_change=save, args=("runware_image_wait_minutes", "runware_wait_input"))
    set_config("app", "runware_image_wait_minutes", wait)
    st.caption("Uma imagem por solicitação. O limite de imagens do vídeo continua valendo. O custo em USD é registrado quando o provedor retorna o resultado; não há teto financeiro prévio implementado. Consulte o saldo e os preços na Runware.")
    if st.button("Consultar referência pública de preços", key="runware_pricing"):
        try:
            st.json(runware.Client.pricing(model))
            st.caption("Referência de preços, sem garantia de cotação para esta solicitação.")
        except runware.RunwareError as exc:
            st.error(str(exc))
    st.markdown("**Teste de uma imagem · pode consumir saldo**")
    prompt = st.text_area("Prompt do teste Runware", value="Documentary illustration of a nineteenth-century steam locomotive, historically accurate, no text.", key="runware_test_prompt")
    pending = st.session_state.get("runware_test_job")
    start = st.button("Gerar 1 imagem de teste (cobrado)", disabled=not key or bool(pending), key="runware_test_start")
    resume = st.button("Consultar / retomar o mesmo teste", disabled=not key or not pending, key="runware_test_resume")
    if start:
        params = VideoParams(video_subject="Teste Runware", video_aspect="16:9", runware_model=model, runware_steps=steps, runware_size=size)
        folder = Path(utils.storage_dir()) / "runware-tests" / str(uuid4())
        pending = {"directory": str(folder), "params": params.model_dump(mode="json"), "prompt": prompt}
        st.session_state.runware_test_job = pending
    if start or resume:
        started = time.monotonic()
        try:
            local_settings = {**settings, "runware_api_key": key, "runware_image_wait_minutes": wait}
            with st.spinner("Aguardando a mesma tarefa Runware…"):
                image, metadata = runware.generate(VideoParams.model_validate(pending["params"]), pending["prompt"], pending["directory"],
                                                   settings=local_settings, existing_only=bool(resume))
            st.session_state.runware_test_result = {"image": str(image), "metadata": metadata, "elapsed": round(time.monotonic()-started, 1)}
            st.session_state.pop("runware_test_job", None)
        except runware.RunwareError as exc:
            st.warning(str(exc))
            if not (Path(pending["directory"]) / "runware-image.json").is_file():
                st.session_state.pop("runware_test_job", None)
            st.caption("O teste fica salvo para consulta; a geração paga não será repetida.")
    result = st.session_state.get("runware_test_result")
    if result:
        st.image(result["image"])
        st.write(f"Tempo desta execução: {result['elapsed']} s")
        st.json(result["metadata"])
    if pending:
        st.caption("Pasta do teste: " + pending["directory"])
