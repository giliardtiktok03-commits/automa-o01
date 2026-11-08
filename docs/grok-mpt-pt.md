# Grok/xAI para imagens no MPT

Grok substitui Runware nas novas gerações e na interface. Pexels, Pixabay e Coverr continuam prioritários no modo misto. AI33 permanece opcional, inicialmente desmarcada. ChatGPT mantém texto, prompts, planejamento e validação visual; geração de imagens OpenAI continua bloqueada.

## Contrato confirmado

A documentação web `docs.x.ai` ficou inacessível nesta sessão. O contrato foi verificado no [SDK oficial xAI](https://github.com/xai-org/xai-sdk-python), versão **1.21.0**, em `src/xai_sdk/sync/image.py`, `image.py`, `client.py` e `sync/client.py`. A chave de imagens usa `grok_image_api_key`, separada da configuração já existente `grok_api_key` para texto. A distribuição foi resolvida e instalada no ambiente de teste; a importação e a assinatura pública foram verificadas.

A implementação usa `xai_sdk.Client` no host padrão oficial `api.x.ai`, autenticado com a chave xAI; chama `client.image.sample(model="grok-imagine-image", prompt=..., image_format="base64", aspect_ratio=...)`. Não implementa endpoints REST presumidos nem usa o site Grok por automação. Retorna uma imagem por chamada, com proporções 16:9, 9:16 e 1:1 correspondentes ao vídeo. Modelo pode ser ajustado pelo usuário conforme disponibilidade da conta.

O SDK permite consultar `respect_moderation`, `base64` e `cost_usd` no resultado. Custo ausente não significa gratuidade. Não há cotação vinculante ou teto financeiro prévio nesta integração; o modo misto prioriza os bancos e permite Grok sem teto de quantidade por padrão (`mixed_grok_unlimited=True`), inclusive na retomada e nos capítulos. O teto numérico só se aplica ao Grok quando essa opção é desativada; AI33 mantém seu limite. O contador de pedidos permanece para auditoria. Saldo da API é separado da assinatura do aplicativo Grok.

## Segurança de execução e recuperação

O SDK vem com repetição automática de algumas falhas de transporte por padrão. O conector a desativa com `grpc.enable_retries=0` e `grpc.service_config={}`. O fechamento do cliente é garantido após a tentativa. Mensagens de erro do provedor não são repassadas integralmente; apenas categorias conhecidas podem aparecer, sem expor chave ou payload.

Cada imagem tem um diretório persistente `mixed/grok-NNN`, com `grok-image.json`. Antes do envio, grava intenção, ID local, modelo e hash do pedido; a chave e o prompt não são gravados nesse registro. O ID local é um identificador de auditoria do MPT, não uma promessa de tarefa consultável na API xAI.

A resposta base64 é salva atomicamente antes de convertê-la para PNG. O sistema valida dimensões, preserva o arquivo e seu hash e reutiliza resultados locais ao retomar. Se houver falha de conexão com resultado desconhecido e nenhuma resposta salva, a retomada interrompe para revisão no painel xAI, sem reenviar ou trocar de gerador automaticamente. Não foi inventado um endpoint de consulta de geração síncrona.

Recusa explícita (`respect_moderation=False`) produz um card editorial identificado, preserva a contagem do pedido e não reformula o prompt. Falhas técnicas interrompem normalmente.

Runware não aparece mais na interface/configuração de exemplo e não pode iniciar novos pedidos. Os campos e o conector antigo permanecem somente para compatibilidade com registros e tarefas já pagas. A remoção não apaga dados, imagens ou credenciais antigas do computador.

## Dependências e instalação

SDK xAI **1.21.0** e `packaging==25.0` estão em `pyproject.toml`, `requirements.txt` e `uv.lock`. Packaging 24.2 era incompatível com a exigência declarada pelo SDK; os demais pacotes que precisaram acompanhar o SDK foram resolvidos no lockfile. Nenhuma chave é distribuída no pacote.

No Windows existente, execute `PREPARAR_GROK_WINDOWS.bat` após extrair a atualização e antes de abrir `webui.bat`. Usa `uv pip` quando disponível, ou `ensurepip`/`pip`. Instalação, teste e rollback: `LEIA-ME-ATUALIZACAO-GROK.txt`.

## Validação

451 testes passaram (1 ignorado) na suíte selecionada de geração, interface Streamlit, recuperação, migração de projetos, Skills, progresso e fila. Há renderização real de um vídeo curto, com resposta do gerador simulada; nenhum teste solicitou imagem paga real. Foram verificados bloqueio de novos pedidos Runware, preservação de imagens antigas, ausência de repetição após timeout, parâmetros do SDK e card de recusa. O lockfile passou em `uv lock --check --offline`.

A velocidade e o custo reais dependem da conta/modelo xAI e devem ser medidos no botão explícito de teste de uma imagem. A suíte ampliada do projeto tem falhas preexistentes registradas na entrega anterior; esta validação não significa que todo teste do repositório tenha passado.

## Atualização: bancos primeiro e Grok sem limite

`mixed_grok_unlimited` é uma preferência operacional, excluída do hash editorial. Alternar a opção não invalida cenas salvas. Em Grok ilimitado, validação e retomada aceitam que o contador exceda `mixed_max_images`, inclusive quando o teto é zero. Toda cena ainda não atendida procura primeiro os bancos habilitados; Grok é usado somente após falta de material aprovado. Pedidos conhecidos e resultados locais continuam recuperados sem reenvio. Não se trata de repetição infinita ou de crédito gratuito: há um pedido por cena ainda necessária, sujeito aos limites reais da xAI.

464 testes passaram na suíte selecionada desta atualização, incluindo retomada com 130 pedidos já contabilizados, teto zero, múltiplos capítulos, prioridade aos bancos e controle opcional de teto na interface. A instalação incremental está em `LEIA-ME-GROK-SEM-LIMITE.txt`.
