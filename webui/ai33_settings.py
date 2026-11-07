"""AI33 settings. Catalog/quote requests occur only on explicit button clicks."""

import hashlib

import streamlit as st

from app.services.ai33 import AI33Client, AI33Error


def render(settings, set_config):
    def save(config_key, widget_key):
        set_config("app", config_key, st.session_state[widget_key])

    st.markdown("**AI33.Pro · Geração de imagens**")
    key = st.text_input(
        "Chave da API AI33.Pro", type="password", value=str(settings.get("ai33_api_key") or ""),
        key="ai33_api_key_input", on_change=save, args=("ai33_api_key", "ai33_api_key_input"),
    ).strip()
    set_config("app", "ai33_api_key", key)
    st.caption("A chave fica na configuração local. Nunca é incluída nos projetos ou prompts. Host: https://api.ai33.pro")
    scope = hashlib.sha256(key.encode()).hexdigest()
    if st.session_state.get("ai33_catalog_scope") != scope:
        st.session_state.pop("ai33_catalog", None)
        st.session_state["ai33_catalog_scope"] = scope
    if st.button("Conectar e carregar modelos AI33", disabled=not key, key="ai33_load_models"):
        try:
            st.session_state["ai33_catalog"] = AI33Client(key).models()
            st.success("Conexão confirmada. Catálogo carregado; nenhuma imagem foi solicitada.")
        except AI33Error as exc:
            st.error(str(exc))
    catalog = st.session_state.get("ai33_catalog", [])
    # Text-only models only. supports_images describes references, not generation.
    usable = [m for m in catalog if m.get("requires_reference_images") is False]
    saved_model = str(settings.get("ai33_image_model") or "bytedance-seedream-4.5")
    if usable:
        options = [m["model_id"] for m in usable]
        model = st.selectbox("Modelo de imagem AI33", options,
                            index=options.index(saved_model) if saved_model in options else 0,
                            key="ai33_image_model_select", on_change=save,
                            args=("ai33_image_model", "ai33_image_model_select"))
    else:
        model = st.text_input("Modelo de imagem AI33", value=saved_model,
                              key="ai33_image_model_input", on_change=save,
                              args=("ai33_image_model", "ai33_image_model_input"))
        st.caption("Carregue o catálogo para selecionar modelos e parâmetros reais da sua conta.")
    set_config("app", "ai33_image_model", model)
    entry = next((m for m in usable if m["model_id"] == model), None)
    selected = {}
    for field, catalog_key, default_key, label, fallback in (
        ("resolution", "resolutions", "default_resolution", "Resolução AI33", "2K"),
        ("quality", "qualities", "default_quality", "Qualidade AI33", ""),
    ):
        config_key = "ai33_image_" + field
        saved = str(settings.get(config_key, fallback) or "")
        widget_key = config_key + "_" + model
        options = list(entry.get(catalog_key, [])) if entry else (["1K", "2K", "4K"] if field == "resolution" else [])
        if not options:
            value = ""
            st.caption(f"{label}: padrão do provedor.")
        else:
            default = saved if saved in options else entry.get(default_key, options[0]) if entry else options[0]
            value = st.selectbox(label, options, index=options.index(default) if default in options else 0,
                                 key=widget_key, on_change=save, args=(config_key, widget_key))
        set_config("app", config_key, value)
        if value:
            selected[field] = value
    cap = st.number_input(
        "Teto da cotação por imagem (créditos AI33)", min_value=0.0,
        value=float(settings.get("ai33_image_max_credits", 1000)), step=10.0,
        key="ai33_image_max_credits_input", on_change=save,
        args=("ai33_image_max_credits", "ai33_image_max_credits_input"),
    )
    set_config("app", "ai33_image_max_credits", cap)
    st.caption("A cotação é verificada antes de cada envio. O provedor não documenta travamento de preço. O limite de imagens do modo misto também se aplica.")
    aspect = st.selectbox("Proporção para consultar preço", ["16:9", "9:16", "1:1"], key="ai33_quote_aspect")
    if st.button("Consultar preço AI33 (sem gerar imagem)", disabled=not key, key="ai33_quote"):
        params = {"aspect_ratio": aspect, **selected}
        try:
            client = AI33Client(key)
            client.validate(model, params, "Documentary illustration")
            estimate = client.price(model, params)
            st.success(f"Cotação: {estimate:g} créditos por imagem.")
            if estimate > cap:
                st.warning("A cotação supera o teto configurado. A geração será bloqueada antes do envio.")
        except AI33Error as exc:
            st.error(str(exc))
