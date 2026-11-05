# Automação editorial por API: Nexlev → adaptações → roteiro

O MPT pode ser usado como componente de uma automação em Python ou de qualquer
ferramenta que faça requisições HTTP. O fluxo completo da API executa as três
etapas, sem pedir aprovação manual entre elas:

1. **Pesquisa:** receber título, link ou transcrição e resultados reais do Nexlev.
2. **Decomposição e switch:** identificar tema, ângulo, formato e promessa;
   propor exatamente três adaptações originais; atribuir pontuações editoriais;
   escolher a melhor e explicar a decisão.
3. **Roteiro:** escrever a narração seguindo a adaptação selecionada, suas
   orientações e os dados de pesquisa. A resposta inclui parâmetros para iniciar
   depois a geração do vídeo no MPT.

## Onde o Nexlev entra

**A automação externa consulta o Nexlev e entrega os resultados ao MPT.** Não há
conector oficial Nexlev configurado neste ambiente, e não foi fornecida uma
especificação de API. Este código não inventa endpoints, não usa uma sessão de
navegador por conta própria e não declara ter feito uma pesquisa on-line.

O campo `nexlev` é um contrato de entrada normalizado para o seu integrador preencher:

- `source`: `nexlev`.
- `observed_at`: data/hora com fuso, por exemplo `2026-11-05T10:00:00Z`.
- `notes`: observações da pesquisa, até 12.000 caracteres.
- `videos`: até 50 registros com `title`, `url` opcional, `views` opcional e
  `channel_median_views` opcional (mediana de visualizações do canal usada como base).
- `demand`: até 30 registros com `keyword`, `search_volume`, `period` e `region`
  opcional. Período e região ficam explícitos; volumes de períodos diferentes
  não são somados automaticamente.
- `recurring_patterns`: até 30 padrões encontrados na pesquisa do Nexlev.

Não é necessário preencher todas as métricas, mas a pesquisa não pode estar vazia.
Quando os dados não existem, a resposta identifica `not_provided` ou
`insufficient_data`. As observações são marcadas como fornecidas pela automação,
sem alegação de verificação independente.

O MPT calcula o indicador de outlier como `views / channel_median_views`, com
limiar padrão de 2. A base precisa ser comparável ao período das visualizações;
a qualidade dessa comparação depende dos dados enviados. A pontuação de cada
adaptação, de 0 a 100, é um julgamento editorial da IA, não uma métrica do Nexlev,
probabilidade de viralização ou garantia de desempenho.

## Referências

`reference` aceita `title`, `url` e/ou `transcript` (até 30.000 caracteres).
Um título basta para a decomposição, com hipóteses explicitamente baseadas nele.
Um link identifica a referência; ele não significa que o vídeo foi assistido.
Se você enviar somente um link, inclua em `nexlev.videos` um resultado com o mesmo
link e seu título, ou acrescente a transcrição. Links YouTube curtos, `/watch`,
`/shorts`, `/live` e `/embed` são associados pelo ID do vídeo. A API não baixa
conteúdo nem acessa destinos arbitrários da URL enviada.

## Executar as três etapas em uma chamada

Inicie a API do MPT pelo fluxo habitual (`uv run python main.py`) e configure
Ollama ou OpenAI no servidor. A seleção `provider` aceita `ollama` (padrão) ou
`openai`, sem fallback automático. As credenciais do provedor permanecem no MPT,
e a API da OpenAI pode gerar cobrança.

1. Envie `POST /api/v1/editorial/workflows` com um JSON conforme
   [editorial-request.json](examples/editorial-request.json).
2. A resposta HTTP **202** contém `workflow_id` e o caminho de consulta.
3. Consulte `GET /api/v1/editorial/workflows/{workflow_id}` até terminar.

O exemplo contém **dados fictícios**, apenas para demonstrar o formato. Substitua
pelos resultados reais do Nexlev. Defina um UUID diferente para cada projeto e
salve esse UUID antes de enviar a primeira requisição.

Se `app.api_key` estiver configurada, use o cabeçalho `x-api-key`. A chave de
acesso ao MPT é diferente da chave da OpenAI. Não envie credenciais dos provedores
no corpo do workflow.

Estados da resposta de consulta:

| `state` | Significado |
|---|---|
| `4` | Na fila ou executando; consulte `stage` e `progress`. |
| `1` | Concluído: `research`, `decomposition`, `script` e `video_params` disponíveis. |
| `-1` | Falhou: consulte `failed_stage` e `error`; etapas concluídas continuam salvas. |

A escolha aparece em `decomposition.selected_id`, com sua justificativa em
`selection_reason`; `approval` fica como `ai_selected`. A seleção deve estar entre
as três propostas e ter a maior pontuação (empates permitem uma das empatadas).
Respostas inválidas do modelo fazem a etapa falhar em vez de avançar com uma
escolha inconsistente.

## Cliente Python incluído

Prepare seu JSON com um `workflow_id` estável e execute:

```bash
uv run python scripts/editorial_pipeline.py \
  --input meu-workflow.json \
  --output resultado-editorial.json \
  --api-url http://127.0.0.1:8080
```

O cliente lê a chave de acesso ao MPT da variável `MPT_API_KEY`, se necessária.
Ele envia uma solicitação, consulta o progresso e salva o relatório completo.
Não há reenvio automático do POST após timeout. O arquivo de saída precisa ser
novo para preservar resultados existentes. Você também pode importar a função
`run_workflow` no seu código.

## Retomada e persistência

Os resultados intermediários ficam em `storage/editorial/<workflow_id>/workflow.json`.
O armazenamento precisa sobreviver a reinícios do processo. Reenvie o **mesmo
JSON e o mesmo `workflow_id`** para retomar uma falha: pesquisa e decisões já
concluídas são reaproveitadas. Uma execução concluída com a mesma entrada não
repete chamadas aos modelos. Se mudar a entrada, use um UUID novo; mudanças sob o
mesmo ID retornam **409**.

Após reiniciar o processo, uma etapa interrompida pode retornar `interrupted: true`;
reenvie a mesma entrada para retomar. Uma tarefa somente enfileirada em memória
precisa ser reenviada após perder o processo. Em instalações Redis, a fila usa
os mecanismos de recuperação já existentes do MPT.

As configurações dos modelos são capturadas quando o trabalho começa; as
credenciais não são gravadas no checkpoint. Mantenha o modelo configurado ao
retomar. Para refazer a decisão usando outro modelo, crie um workflow novo.

A retomada reaproveita apenas etapas cujo resultado foi salvo com sucesso.
Uma interrupção entre a resposta do provedor e a gravação local pode exigir
repetir essa chamada. As etapas não são reenviadas automaticamente após falha.

## Prosseguir para o vídeo

`video_params` contém o título escolhido, o roteiro gerado, o idioma e a meta de
duração. Combine esse objeto com suas configurações de voz, imagens, legendas e
música e envie ao endpoint existente `POST /api/v1/videos`.

A geração de vídeo não é disparada pela etapa de roteiro. Sua automação controla
esse próximo passo. A duração do roteiro é uma meta textual; o vídeo real continua
dependendo da narração e da validação do modo por capítulos.

## Endpoints individuais

| Endpoint | Entrada | Saída |
|---|---|---|
| `POST /api/v1/editorial/research` | `reference`, `nexlev`, `target_topic`, `outlier_threshold` | Pesquisa normalizada e indicadores calculados. |
| `POST /api/v1/editorial/decompose` | Pesquisa acima + `provider`, `language`, `requirements` | Três propostas e escolha automática. |
| `POST /api/v1/editorial/scripts` | Mesmos dados + `decision` + `target_duration_minutes` | Roteiro e `video_params`. |

Os contratos completos aparecem no OpenAPI do servidor. Para encadear as três
etapas sem gerenciar respostas intermediárias, prefira `/editorial/workflows`.
A pesquisa leve da interface continua disponível como ferramenta independente;
o encadeamento novo é oferecido pela API para a automação externa.

## Validação e pendências

Os testes usam chamadas simuladas aos modelos e cobrem dados ausentes, outliers,
três propostas, seleção coerente, roteiro baseado na escolhida, autenticação HTTP,
fila, Redis, conflitos de ID, persistência e retomada. Não houve consulta real ao
Nexlev nem teste com chave real da OpenAI/Ollama neste trabalho. A coleta no Nexlev
precisa ser conectada no seu orquestrador com o acesso/documentação desse serviço.
