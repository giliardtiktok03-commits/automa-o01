# Runware no MoneyPrinterTurbo

O modo misto prioriza os bancos existentes e usa Runware para imagens novas quando necessário. AI33 começa desmarcada, sem apagar credenciais, arquivos ou tarefas remotas. Se ambas forem selecionadas, Runware tem prioridade; erros não acionam outro gerador. A API OpenAI continua disponível para texto e análise visual, com geração de imagens bloqueada.

## Contrato verificado

Referências oficiais consultadas: [SDK Python Runware](https://github.com/runware/runware-python), especialmente `runware/transport/rest.py`, `runware/client.py`, `runware/types/task_map.py` e `runware/content.py`.

| Operação | Contrato utilizado |
|---|---|
| Transporte | `POST https://api.runware.ai/v1`, corpo JSON em array, `Authorization: Bearer <chave>` |
| Imagem | `taskType: imageInference`, `taskUUID`, `model` AIR, `positivePrompt`, `width`, `height`, `numberResults: 1`, `deliveryMethod: async`, `outputType: URL`, `outputFormat: PNG`, `includeCost: true`; `steps` opcional |
| Consulta | Mesmo endpoint com `taskType: getResponse` e o UUID original |
| Modelos | `taskType: modelSearch`, UUID próprio, `search`, `source: official`, `category: checkpoint`, `limit: 20`, `offset: 0` |
| Referência de preços | `GET https://content.runware.ai/models/{AIR-codificado}/pricing`, sem autenticação |

Inicial: `runware:100@1` (FLUX.1 Schnell), 4 passos, 1024×576 para 16:9. Retrato e quadrado respeitam a proporção escolhida. A opção 2048 exige compatibilidade do modelo. Modelos diferentes podem requerer outros parâmetros; esta etapa cobre geração texto→imagem com resolução e passos, sem referências, áudio ou vídeo.

Uma resposta inicial pode conter `data: []`; isso é uma confirmação assíncrona, seguida de consultas. O resultado precisa corresponder ao UUID solicitado e conter uma única `imageURL`. Custos numéricos retornados em `cost` são registrados como `cost_usd`. Não há endpoint de cotação vinculante/teto por solicitação implementado; a referência pública não garante o preço da configuração. O limite de solicitações de imagens do MPT permanece válido, inclusive entre capítulos.

## Persistência e retomada

Cada cena usa `mixed/runware-NNN/runware-image.json`. O UUID é gravado atomicamente antes do envio pago. Uma retomada faz apenas `getResponse` com o mesmo UUID; nunca repete `imageInference` após resposta perdida. Configurações e prompt participam do hash de integridade; a chave e URLs assinadas não entram no registro. Imagens baixadas são verificadas, convertidas para PNG e gravadas atomicamente com hash. Downloads não recebem a chave da API.

Registros de cenas preservam o gerador e seus parâmetros. Mudar a seleção do gerador afeta solicitações novas; imagens anteriores são reutilizadas. Uma solicitação AI33 paga e pendente continua consultada na AI33 mesmo quando desmarcada. Sem registro válido, o sistema interrompe para reconciliação, sem cobrança automática adicional. Não se pode cancelar uma tarefa remota apenas apagando arquivos locais.

A espera é configurável (Runware: 10 minutos; AI33: 45 minutos). Se houver tarefa conhecida ainda pendente, o projeto entra em estado `TASK_STATE_WAITING`, preserva o ID e oferece retomada; falhas técnicas seguem o tratamento de erros. Isso não acelera o provedor. A velocidade só pode ser medida com um teste real autorizado na conta do usuário.

## Interface e verificação

`Configurar fontes de material → Imagens IA → Runware`: chave mascarada, AIR, passos, tamanho, espera, busca de modelos, referência de preços e teste explícito de uma imagem que pode consumir saldo. A consulta e a geração só acontecem mediante clique. O teste salvo pode ser retomado sem reenviar a solicitação. Chaves ficam na configuração local; não compartilhe `config.toml`.

Cobertura automatizada inclui contrato HTTP simulado, resposta assíncrona, recuperação após perda da resposta, limites, ausência de fallback, retomada de tarefas AI33 antigas, configuração Streamlit e renderização real de um vídeo curto com a fonte Runware simulada. Nenhum teste automatizado usa saldo real.

Instalação e rollback: veja `LEIA-ME-ATUALIZACAO-RUNWARE.txt`. O ZIP preserva as personalizações existentes e não inclui configuração local, mídia ou ambiente virtual.

### Resultado da validação desta entrega

323 testes passaram na suíte de integração (Runware, AI33, modo misto, retomada, capítulos, Skills, configurações e progresso), incluindo renderização real curta com provedor simulado. A migração da seleção previamente salva de AI33 foi conferida na interface, inclusive a possibilidade de reativá-la explicitamente.

A suíte ampliada de fila, histórico, tarefas e CLI apresentou 230 testes passando, 3 ignorados e 7 falhas já existentes, reproduzidas também no commit anterior `6d05ab8`: comparações de instantâneos após publicação das métricas, expectativa do antigo provedor Sonilo e aceitação de geração OpenAI que já está bloqueada. Não foram atribuídas à integração Runware nem corrigidas fora deste escopo.
