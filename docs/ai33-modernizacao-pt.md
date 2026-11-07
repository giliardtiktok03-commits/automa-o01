# Modernização AI33.Pro — entrega 1: núcleo isolado

> Registro da primeira entrega. Para a versão integrada à interface e ao modo
> misto, consulte [AI33 no MPT](ai33-mpt-pt.md).

## Escopo desta entrega

Base de rollback: `a73a901127df853fd6d316a8e63764192e23ddb4`.
Implementadas as etapas 1 e 2 do plano aprovado: registro da base e conector
isolado de imagens. Nenhum provedor, configuração, segredo, projeto salvo ou
componente da interface existente foi substituído. Não foram instaladas
dependências. Esta entrega **ainda não altera a geração pela interface**.

A migração do fluxo de produção deverá ocorrer na etapa 3. Nessa etapa, toda
nova imagem sintética será exclusivamente AI33, sem fallback OpenAI, Flow ou
Codex. Imagens antigas continuarão reutilizáveis. ChatGPT continuará responsável
pelo planejamento e pela análise editorial, inclusive pela validação visual.

## Contrato utilizado

Fonte: documentação de imagens fornecida pelo usuário em 07/11/2026,
originária de https://ai33.pro/app/api-document. A página não pôde ser
revalidada neste ambiente por restrição de rede. Testes desta entrega usam
respostas simuladas; não houve geração paga nem validação de uma conta real.

| Operação implementada | Método e caminho |
|---|---|
| Catálogo | `GET /v1i/models` |
| Cotação | `POST /v1i/task/price` — JSON |
| Geração | `POST /v1i/task/generate-image` — multipart |
| Estado e resultado | `GET /v1/task/{task_id}` |

Host fixo `https://api.ai33.pro`, autenticação `xi-api-key`.
O catálogo confirma modelo, proporções, resoluções e suporte sem referências.
Esta entrega gera **uma imagem por tarefa, somente texto**, prompt de até
4.000 caracteres, sem assets e sem webhook. Não infere capacidades de áudio
a partir da existência do catálogo de imagens.

`GET /v1/tasks` e `POST /v1/task/delete` estão documentados, mas não foram
implementados neste núcleo. Nenhuma tarefa remota é apagada automaticamente.
TTS, STT, música, SFX, dublagem, múltiplas vozes, clonagem, transformação e
dicionários seguem pendentes de contratos oficiais verificáveis.

## Arquivos e responsabilidades

| Arquivo | Responsabilidade |
|---|---|
| `app/services/ai33/client.py` | HTTP, catálogo, validação, cotação, envio e consulta |
| `app/services/ai33/images.py` | checkpoint, exclusão mútua, retomada e arquivo PNG |
| `app/services/ai33/__main__.py` | teste local explícito fora do pipeline |
| `test/services/test_ai33_images.py` | contrato, falhas, retomada e download |

Não há chamadas de rede ao importar o módulo ou abrir o MPT.

## Uso local opcional

Não é necessário testar geração paga para instalar esta entrega. Para testar,
configure `AI33_API_KEY` no ambiente **do próprio computador**, sem colocar a
chave em comandos compartilhados, screenshots, arquivos versionados ou no chat.
No PowerShell, na raiz do MPT, com a variável já configurada:

```powershell
.\.venv\Scripts\python.exe -m app.services.ai33 models
.\.venv\Scripts\python.exe -m app.services.ai33 price --model ID_DO_CATALOGO
```

Os padrões são `16:9` e `2K`; altere `--aspect-ratio` e `--resolution` se o
catálogo do modelo exigir outros valores. A cotação não gera uma imagem.

Somente para uma geração paga deliberada, salve o prompt em `prompt.txt` e use
um teto de créditos escolhido por você a partir da cotação:

```powershell
.\.venv\Scripts\python.exe -m app.services.ai33 generate --model ID_DO_CATALOGO --prompt-file prompt.txt --directory storage/ai33-test/imagem-01 --max-credits SEU_TETO
```

`SEU_TETO` é um número de créditos, não reais ou dólares. Não há tarifa fixa
codificada. A documentação não garante validade ou travamento da cotação; o
teto bloqueia estimativas maiores antes do envio, mas não é um teto de cobrança
imposto ao servidor. Os exemplos documentais não constituem preços garantidos.

Cada diretório corresponde a **uma imagem pretendida**. Para retomar, repita
o mesmo comando com o mesmo diretório, modelo, parâmetros e prompt. Não apague
o checkpoint nem troque o diretório para contornar um envio não confirmado.

## Retomada e segurança financeira

1. Valida o catálogo e consulta a cotação.
2. Verifica o teto autorizado antes da solicitação paga.
3. Grava intenção em disco, com escrita atômica e `fsync`, antes do POST.
4. Salva imediatamente o `task_id` recebido.
5. Consulta a cada quatro segundos, por até 150 consultas por execução.
6. Baixa o resultado, valida a imagem e salva PNG com SHA-256.

Um lock por diretório impede dois processos de enviarem a mesma tarefa juntos.
Timeout, resposta ambígua ou falha de gravação após envio não provocam um novo
POST automático. Se não houver ID recuperável, é necessário reconciliar a
tarefa no painel do provedor antes de decidir por outra geração. A API não
documenta chave de idempotência, portanto não se promete exatamente uma cobrança
em qualquer cenário de falha.

Com ID conhecido, falhas de consulta/download e encerramento do processo
permitem retomar a mesma tarefa. Arquivo íntegro é reutilizado sem rede;
arquivo ausente ou alterado é baixado novamente. Um prompt diferente é
recusado no mesmo checkpoint. Cada novo envio exige outro diretório deliberado.

Consultas GET de tarefa repetem falhas temporárias 429/502/503/504 ou falhas
de conexão/timeout até quatro tentativas, com intervalos de 4, 8 e 16 segundos.
`Retry-After` em segundos ou data é respeitado; espera superior a 60 segundos
interrompe a execução para retomada posterior. POST de geração nunca é repetido
automaticamente. Erros de autenticação, JSON e identidade não são repetidos.
Se a consulta continuar indisponível, o checkpoint permanece intacto.
Falha remota genérica não é classificada como recusa de
segurança. Reembolso descrito pelo provedor não é presumido como confirmado.

Downloads não recebem a chave AI33; exigem HTTPS público, verificam cada
redirecionamento e limitam bytes, pixels e quantidade de redirects. A resolução
DNS é verificada antes de conectar; ambientes que exigem proteção completa
contra rebinding devem impor também regras de saída na rede/proxy.
URLs assinadas, prompt e chave não são gravados no checkpoint. Não se registram
corpos de erro remotos, que podem conter dados sensíveis.

## Base preservada e próximos passos

| Personalização existente | Arquivos principais a preservar na migração |
|---|---|
| Interface em colunas, cores, configurações | `webui/Main.py`, `webui/settings_providers.py` |
| ChatGPT, roteiro e editorial | `llm.py`, `editorial.py`, `reference_research.py` |
| Bancos de vídeo e imagens antigas | `material.py`, `mixed_materials.py` |
| Validação visual, ritmo e não repetição | `visual_validation.py`, `mixed_materials.py` |
| Áudio externo, vozes e legendas | `narration.py`, `voice.py`, `subtitle.py` |
| Música e renderização | `bgm.py`, `video.py`, `elevenlabs_music.py`, `sonilo.py` |
| Projetos, orçamento, capítulos e fila | `mixed_resume.py`, `long_form.py`, `webui_task.py`, `task_artifacts.py` |
| Configuração e modelos | `app/config/config.py`, `app/models/schema.py` |

Serviços da tabela ficam em `app/services/`, salvo caminhos explícitos.
Os próximos incrementos do plano aprovado são:

1. Integração AI33 no modo misto e bloqueio de toda geração sintética antiga;
   configuração local da chave e seleção real de modelos, sem segredos no projeto.
2. Continuidade de projetos antigos, snapshots e orçamento cumulativo entre
   capítulos, mantendo proveniência original e registrando a nova continuação.
3. Bloco `00 · Configurações de Skills`, acima do roteiro na primeira coluna;
   instruções declarativas, múltiplas skills, conflitos explícitos e snapshot
   de conteúdo/hash por trabalho, preservando o modo sem skills.
4. Curadoria histórica Commons, depois LOC/NARA, com licença por arquivo,
   créditos e identificação de reconstruções.
5. Identidade vocal aprovada pelo usuário e demais serviços somente após
   documentação verificável dos endpoints correspondentes.

Testes de regressão devem cobrir modo misto, retomada, capítulos, fila, validação
visual e artefatos. Não executar chamadas pagas na suíte. Antes de mudar o
pipeline, acrescentar testes que impeçam OpenAI Image, Codex e Flow de gerar
novas imagens em qualquer rota, preservando a leitura dos materiais existentes.

## Rollback

Esta entrega só adiciona arquivos: removê-los restaura o comportamento anterior.
Em futuras etapas, usar commits pequenos e reversíveis. Fazer backup local de
configuração e `storage` sem publicá-los. Não apagar imagens, checkpoints nem
IDs remotos; voltar código não desfaz custos já realizados. Nenhuma migração
de projeto deve sobrescrever o manifesto anterior sem backup explícito.
