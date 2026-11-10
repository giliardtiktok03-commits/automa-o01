# Relatório de implementação — Historical Archive Finder

Escopo aplicado: especificação 1.0 do pacote, com as instruções posteriores do usuário:
**sem aprovação manual**, com fallback automático para **reconstrução ilustrativa
pela IA já habilitada**. O módulo começa OFF.

## Arquivos existentes modificados

- `app/models/schema.py`: flags internas de montagem/retomada histórica.
- `app/services/task.py`: entrada global, contexto de áudio/SRT e montagem dos clipes.
- `app/services/mixed_materials.py`: acervo antes de stock/IA, proveniência e créditos usados-only.
- `app/services/long_form.py`: compatibilidade dos fingerprints e capítulos existentes.
- `webui/Main.py`: painel global e indicadores de candidatos/fontes.
- `config.example.toml`: defaults OFF e limites, sem credenciais reais.
- `test/services/test_mixed_materials.py`: integração e fallback automático para IA.
- `test/services/test_webui_headless_task_actions.py`: atualização de expectativas antigas
  para os controles Flow/fontes/limites que já existiam nesta versão personalizada.

## Módulos adicionados

- `app/services/historical_archive/contracts.py`: contratos e preferências.
- `settings.py`: leitura global/live, default OFF.
- `network.py`: hosts oficiais, cache, pacing, timeouts, backoff e Retry-After.
- `providers/{loc,nara,wikimedia}.py`: conectores independentes e normalização.
- `providers/common.py` e `providers/__init__.py`: helpers e registro de providers.
- `query_builder.py`: consultas por cena e controle de datas/equipamentos.
- `ranker.py`: correspondência editorial explicável.
- `rights.py`: política automática de reutilização.
- `downloader.py`: validação por conteúdo e arquivos atômicos.
- `manifest.py`: resultados, buscas e créditos somente usados.
- `service.py`: orquestração, limites e seleção automática.
- `pipeline.py`: adaptação ao renderizador/retomada existentes.
- `research.py`: pesquisa editorial cancelável em segundo plano.
- `__init__.py`: API do módulo.
- `webui/historical_archive_settings.py`: controles e auditoria, sem aprovações.
- `test/services/test_historical_archive.py`: testes do módulo e renderização real.
- `docs/historical-archive-finder-pt.md`: uso, contrato, limitações e rollback.

## Resultado e limites

Implementados toggle global, três conectores, pesquisa por cena, ranking, direitos,
download/organização, cache, cancelamento, integração global e mista, seleção sem
aprovação, fallback e proveniência de reconstruções. As fontes pré-existentes e seus
limites permanecem ativos conforme as escolhas anteriores do usuário.

Europeana/Internet Archive estão marcados como pendentes. Testes autenticados nas APIs
reais não foram possíveis na rede do ambiente; fixtures não provam disponibilidade
ou todos os formatos de resposta da produção. PDF sem preview/conversor e documentos
multipágina/OCR têm limitações explicitadas no manual.

Os testes locais usam respostas simuladas para a rede e executam FFmpeg real para
validar clipes horizontais/verticais e montagem. Não há cobrança de API nos testes.

## Validação executada

**390 testes passaram, 20 subtestes passaram e 3 testes opcionais de API real foram
pulados** (sem opt-in de rede/credenciais). Inclui a nova política sem aprovação e
IA como reconstrução ilustrativa, além de regressão de DeepInfra, Grok, Flow, AI33,
retomada, capítulos, fontes, gerenciador e interface.

Arquivos de teste executados: `test_historical_archive.py`, `test_mixed_materials.py`,
`test_long_form.py`, `test_mixed_resume.py`, `test_webui_grouped_select.py`,
`test_deepinfra_image.py`, `test_grok_image.py`, `test_google_flow.py`,
`test_material_source_preflight.py`, `test_task_manager.py`,
`test_webui_headless_task_actions.py`, `test_settings_providers.py` e
`test_ai33_production.py`. A compilação Python e `git diff --check` também passaram.

Os testes reais podem ser habilitados explicitamente com `MPT_ARCHIVE_LIVE_TESTS=1`
e, para NARA, `NARA_API_KEY`; eles fazem consultas, sem downloads de originais ou
chamadas de geração paga. Não foram executados nesta entrega.


## Substituição do conector LOC por serviços públicos

Mantida uma única fonte `loc`, com três clientes públicos em
`app/services/historical_archive/providers/loc_services.py`: `LOCMetadataService`,
`LOCImageService` e `LOCTextService`. `providers/loc.py` foi substituído para coordená-los.
Não foi criado campo de chave LOC. A chave NARA existente não sofreu alteração.

Outros arquivos desta revisão: `contracts.py` (limites/preferências), `network.py`
(quotas persistentes/cooldown), `service.py` (OCR por cena e deduplicação entre versões
redimensionadas do mesmo registro), `webui/historical_archive_settings.py`,
`config.example.toml`, documentação e testes. Foi adicionado
`test/services/test_loc_public_services.py`.

**Validação desta revisão:** 422 testes passaram, 20 subtestes passaram e 3 testes reais
opcionais ficaram pulados. Inclui os tetos 20/150/150/min, contagem de retries,
coordenação entre clientes, bloqueio de todos os serviços LOC durante cooldown,
Retry-After em data HTTP, OCR e segurança XML, direitos, IIIF e regressão do MPT.
A compilação Python e `git diff --check` passaram.

Pendência mantida: teste real dos serviços na rede do usuário, especialmente registros
com OCR; não há garantia de OCR para todo documento digitalizado. O acesso direto à
LOC foi bloqueado no ambiente e isso não foi contornado.
