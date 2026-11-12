# Retomada quando a API de validação visual falha

O erro `Visual API failed or returned an invalid verdict; no candidate was approved`
era tratado como interrupção definitiva no modo misto. Assim, uma falha técnica
na avaliação de um vídeo do banco impedia chegar ao DeepInfra selecionado.

Esta correção distingue falha técnica de parecer válido reprovando o vídeo.
Não aprova material sem uma avaliação válida e não desativa a validação visual.

## Comportamento

1. Extrai os mesmos três frames reduzidos e usa o mesmo modelo visual configurado.
2. Reaproveita os pareceres já salvos em `visual-checks.json`.
3. Para timeout, conexão, erro de serviço ou resposta fora do formato, permite
   no máximo **duas chamadas explícitas** (tentativa inicial + uma repetição).
   O SDK continua com `max_retries=0`. Cada avaliação pode consumir tokens.
4. Autenticação, limite HTTP 429 e requisição/modelo inválido não são repetidos
   automaticamente. O status/categoria é registrado sem expor credenciais.
5. Se ainda não houver parecer válido e **DeepInfra já estiver selecionado**, o
   vídeo do banco permanece sem aprovação e esse corte segue para o fluxo de
   imagens DeepInfra existente. O limite de imagens continua sendo verificado
   antes do envio. A opção sem teto continua sendo a que o usuário já configurou.
6. O modelo de imagem é o congelado no projeto/solicitação. Se for
   `PrunaAI/p-image`, esse modelo será usado; a correção não troca modelos de
   trabalhos antigos silenciosamente.

Um parecer válido com `relevant=false` continua procurando outro candidato nos
bancos normalmente. Uma falha técnica persistente da API visual encerra as
consultas desse corte e permite o DeepInfra selecionado, sem fingir que houve
aprovação ou reprovação semântica.

Se DeepInfra não estiver selecionado, a produção continua interrompendo com erro
claro: não é ativado outro gerador por conta própria. Falhas locais de leitura ou
extração de frames também não são convertidas em falhas da API e não disparam
esse fallback pago.

O prompt de avaliação foi preservado. O orçamento de saída do parecer subiu de
250 para 450 tokens, e JSON com cercas Markdown é normalizado pelo helper já
existente. Os critérios de relevância, confiança mínima e campos obrigatórios
permanecem os mesmos.

## Diagnóstico

As falhas passam a ser registradas em:

`storage/tasks/<id>/mixed/visual-errors.json`

O arquivo contém categoria, HTTP quando disponível, tentativa, cena, modelo e
`approved=false`. Para erros de validação de campos, registra nome/tipo do campo
inválido, sem copiar o conteúdo da resposta. Categorias incluem `timeout`,
`connection`, `invalid_verdict`, `authentication`, `rate_limit` e `invalid_request`.

Este arquivo é um histórico de tentativas com erro, não o resultado final de
aprovação: uma nova tentativa pode ter obtido um parecer válido. Os pareceres
válidos continuam em `visual-checks.json`. A quantidade histórica fica limitada
a 20 registros por impressão do candidato/contexto.

O terminal mostra avisos com categoria/status/tentativa e informa quando a cena
vai para o DeepInfra. O manifesto também identifica a falha técnica que levou ao
fallback. Não se registra a chave, os cabeçalhos ou mensagens brutas do SDK.

A correção permite continuar e melhora o diagnóstico, mas não demonstra a causa
exata da resposta inválida anterior: o log enviado não continha essa resposta.
Problemas de saldo, acesso ou disponibilidade das APIs ainda dependem da conta.

## Instalação e retomada no Windows

1. Feche o servidor do MPT e faça backup do código e de `storage`.
2. Extraia o ZIP incremental na raiz do MPT. Ele substitui somente:
   - `app/services/visual_validation.py`
   - `app/services/mixed_materials.py`
3. Preserve integralmente a pasta do projeto que falhou, incluindo áudio,
   roteiro, `mixed-scenes.json`, `mixed-plan-progress.json` e a pasta `mixed`.
4. Reabra o MPT e retome **o mesmo projeto salvo**. Não é necessário iniciar uma
   produção nova nem gerar a narração novamente.
5. Mantenha DeepInfra como gerador escolhido e a autorização/limite já desejados.
   Se o resultado não puder ser confirmado, os ledgers existentes continuam
   impedindo reenviar silenciosamente uma imagem já solicitada.

A retomada reaproveita o planejamento e materiais completos que continuarem
válidos no disco. Não apague checkpoints para tentar forçar a execução.

Roteiro, narração, pesquisas/downloads dos bancos, zoom, layout e configurações
salvas não foram alterados. Os clientes Pexels/Pixabay e o conector DeepInfra não
foram reimplementados. Nenhuma chave ou dado de projeto acompanha o ZIP.

## Validação

131 testes locais aprovados; um teste antigo opcional de API DeepInfra ao vivo
não foi executado. Cobertura: repetição limitada com recuperação, JSON inválido,
JSON cercado, categorias HTTP, ausência de segredos nos diagnósticos, uso do
PrunaAI já selecionado, preservação do primeiro corte aprovado, retomada sem nova
imagem, limite de imagens, ausência de fallback para outros geradores e falhas
locais de frames. A regressão inclui planejamento/materiais/retomada e todos os
testes DeepInfra/FLUX/SDXL/P-Image existentes.

Os testes usam respostas de API simuladas e também renderização/leitura local de
clipes. Nenhuma geração paga foi executada neste ambiente. A conferência com a
conta real ocorrerá ao retomar o projeto no Windows.
