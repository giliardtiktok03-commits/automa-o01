# Beyond the Archives — Story Intelligence · direção editorial GPT

Instalado dentro de **00 · Configurações de Skills**, na primeira coluna do MPT.
A skill incluída é **Beyond the Archives — Editorial Director**. Ela é instalada
na biblioteca local na primeira abertura, mas não é ativada automaticamente.
Não substitui outras skills, a voz aprovada, as fontes visuais nem configurações
existentes. Não acrescenta dependências ou migrações de banco.

## Como testar sem gerar vídeo

1. Ative **Ativar Skills editoriais** e selecione a skill acima. Para ser a
   diretriz editorial principal, selecione-a primeiro.
2. Expanda **Beyond the Archives · Story Intelligence** dentro do mesmo bloco.
3. Preencha **Topic or Working Title**, duração e, opcionalmente, o recorte.
4. Clique **Analyze Story · Analisar tema**.
5. Explore Channel Memory, Narrative Strategy, Research & Evidence e Episode
   Blueprint. Edite o JSON do blueprint para ajustar motor, pergunta, beats,
   fontes e ressalvas. Valide e salve revisões na biblioteca editorial.

A análise principal agora é **GPT pela OpenAI**, selecionada automaticamente quando
há chave e modelo OpenAI disponíveis. Ela usa a integração LLM existente do MPT,
incluindo o modelo e a Base URL OpenAI configurados. A escolha é feita em uma cópia
por solicitação; não muda o provedor global usado pelos outros módulos. OPENAI_API_KEY
também pode fornecer a chave localmente. Nenhuma credencial entra no blueprint.

O GPT recebe tema/recorte, duração, regras editoriais da skill, inventário completo
disponível e fontes/trechos fornecidos. Não recebe a escolha de motor ou os beats
genéricos do sistema local como resposta sugerida: deve avaliar o potencial,
selecionar a forma documental, justificar alternativas, identificar conflitos,
progressão causal, ritmo, desfecho e necessidades de pesquisa.

Em **Modo da análise editorial**, o padrão é **Automático · GPT pela OpenAI**.
**Análise local simplificada** permite optar pelas regras iniciais sem uma chamada
remota. Sem configuração OpenAI, o modo automático usa essa análise simplificada
e mostra o motivo. Se uma solicitação GPT falhar ou retornar um contrato inválido,
a interface oferece **Executar análise local simplificada**. Isso exige uma ação
explícita e não envia outra requisição à API. O relatório nunca identifica resultado
local como análise GPT.

Cada análise GPT envia uma solicitação pelo adaptador existente, com timeout de
120 segundos e sem retry automático. Pode haver custo de texto. O modelo não
ganha acesso automático à internet; fontes e trechos precisam ser fornecidos.
Este módulo não busca arquivos nem baixa imagens. Nem a análise nem sua aprovação
iniciam automaticamente roteiro completo, task.py, áudio ou vídeo.

O painel continua usando as abas Channel Memory, Narrative Strategy,
Research & Evidence e **Narrative Blueprint**. Esta última permite editar o plano,
validar, aprovar, salvar revisões e exportar. O formato EpisodeBlueprint e o nome
legacy episode-blueprint.json são preservados para compatibilidade.

## Memória editorial

O inventário inicial enviado pelo proprietário contém três vídeos publicados:
história geral do GRU, Project Azorian e Project Iceworm. Datas, URLs, métricas e
roteiros continuam ausentes; arquétipos atribuídos aos títulos são provisórios.
A memória distingue published, scheduled, in_production, planned e archived.
Published/scheduled/in_production participam da prevenção de duplicatas; planned
produz alerta; archived não é tratado como vídeo novo em produção.

A comparação local usa títulos, assuntos e aliases, com justificativas explícitas.
Não é uma busca semântica exaustiva. O GPT pode aprofundar diferenças,
mas não anula duplicatas detectadas. Para recortes novos sobre entidades já
abordadas, descreva um evento/pergunta concretamente distintos e revise essa
justificativa. Um título idêntico a um publicado continua bloqueado.

A aba Channel Memory permite editar o inventário. Mudanças para publicado ou
agendado exigem confirmação explícita nessa tela; salvar um blueprint só permite
planned ou in_production. O próprio episódio carregado não duplica a si mesmo,
mas continua sendo detectado em outras propostas. Atualizações do pacote não
sobrescrevem inventários ou SKILL.md editados e não desfazem arquivamentos.

## Evidências e aprovação para roteiro

Fontes opcionais são uma lista JSON. Exemplo de formato (preencher com documentos
reais, não copiar os placeholders como evidência):

```json
[
  {
    "id": "fonte-1",
    "title": "Título real do documento",
    "url": "",
    "excerpt": "Trecho real relevante",
    "interpretation": "documented"
  }
]
```

Interpretation aceita documented, disputed, hypothesis ou unknown. Provenance é
sempre user_supplied: o módulo não autentica documentos. Cada beat deve conter
source_ids existentes e confidence verified ou supported_but_disputed após
revisão. Verified significa revisado com base nas fontes fornecidas; não significa
validação independente pelo MPT. Hipóteses e fontes desconhecidas não liberam o
roteiro. Fontes em disputa preservam ressalva de atribuição e versões concorrentes.
O modelo não pode acrescentar fontes ao registro nem aprovar o próprio trabalho.

O Narrative Blueprint contém narrative_potential, central_conflicts,
progression_strategy, ending_strategy e pacing_strategy. O registro claim_register
separa documented_fact, allegation, inference e research_gap. Alegações precisam
de atribuição; inferências devem apresentar a evidência e sua ressalva.

Fatos documentados precisam citar IDs realmente fornecidos e evidence_quotes com
excertos presentes nas fontes. Referências inexistentes ou citações incompatíveis
são descartadas e a afirmação passa a lacuna de pesquisa. Essa verificação textual
não autentica o documento nem prova que o modelo interpretou o trecho corretamente;
a revisão humana continua obrigatória. Alterações de fontes propostas pelo modelo
não substituem o registro original. Lacunas centrais bloqueiam a aprovação; dúvidas
não centrais podem permanecer explicitamente sinalizadas.

Sem suporte para afirmações centrais, o estado é research_required. Duplicatas ou
recortes ainda indefinidos ficam needs_revision. O botão **Validar revisão
editorial** considera fontes, beats repetidos, faixa de palavras e novidade; a
revisão humana também confere promessa, progressão, conclusão e ressalvas. Só
então é habilitado **Approve for Script · Aprovar para roteiro**.

Depois da aprovação, use exatamente o input_topic no campo **Tema do vídeo**.
O blueprint vai para a cópia imutável da skill do projeto, com o hash existente.
Não é colado como texto falado. O roteiro continua pelo gerador atual e preserva
a promessa, fontes e incertezas; o idioma criativo recomendado é inglês americano.
O escritor de capítulos também recebe o contexto aprovado. Nenhuma voz é trocada.
Mudança de tema, revisão do plano ou alteração da memória exige nova aprovação.
Projetos já enviados conservam a cópia original, mesmo se a skill for editada ou
arquivada depois. Sem esta skill ativa, a geração padrão permanece disponível.

## Armazenamento e rollback

- Biblioteca existente: storage/channel-skills/beyond-the-archives/SKILL.md.
- Memória: channel_memory/published_videos.json dentro dessa pasta.
- Histórico da memória: channel_memory/revisions/.
- Planos: blueprints/<id>/latest.json e revision-0001.json, etc.
- Exporte JSON e relatório Markdown pelos botões do painel.

Feche o MPT antes de substituir código. Faça backup e extraia o pacote na raiz;
reabra webui.bat. O ZIP não contém .venv, storage ou config.toml real. Para desligar,
remova a seleção da skill ou desative Skills editoriais. Para rollback de código,
feche o MPT e restaure o backup, preservando storage e configurações.

## Arquivos da implementação

Novos:
- app/models/story_intelligence.py: contrato tipado de blueprint, beats e fontes.
- app/services/story_intelligence.py: memória, análise, revisão, persistência e
  contexto aprovado, reutilizando biblioteca, snapshots e gravador atômico existentes.
- webui/story_intelligence.py: painel integrado às Skills.
- resource/channel-skills/beyond-the-archives/: SKILL.md, inventário inicial e
  especificação fornecida pelo usuário.
- test/services/test_story_intelligence.py e test/services/test_story_intelligence_gpt.py: aceitação, integração simulada e teste real opt-in.

Alterados: webui/channel_skills.py, webui/Main.py,
app/services/channel_skill_runtime.py, app/services/llm.py,
app/services/task.py, app/services/long_form.py,
test/services/test_channel_skills.py e documentação/pacotes.

O teste de fingerprint antigo das skills foi atualizado para considerar os campos
inativos de arquivos históricos e DeepInfra que já existiam antes desta alteração.
O teste de arquivamento passa a selecionar explicitamente a skill a arquivar,
preservando a nova skill instalada junto dela.

Saída real do modo local: docs/examples/bta-operation-gold-blueprint.json.
Ela é um plano provisório com tarefas de pesquisa, não uma pesquisa histórica
concluída. Nenhuma chamada paga ou teste com evidência histórica real foi executado.


## Executar testes de desenvolvimento

```powershell
.\.venv\Scripts\python.exe -m pytest -q test/services/test_story_intelligence.py test/services/test_story_intelligence_gpt.py test/services/test_channel_skills.py test/services/test_long_form.py
```

Os testes de UI usam Streamlit AppTest. O teste do modelo central substitui a
chamada remota por respostas controladas para verificar o contrato, as fontes e
a rejeição de aprovações inventadas; não comprova qualidade factual de um modelo real.

## Validação da versão anterior (instalação inicial)

- 509 testes passaram, 3 foram ignorados e 20 subtestes passaram na regressão de
  skills, roteiro, capítulos, arquivos históricos, montagem e provedores atuais.
- Outros 10 testes da API editorial passaram em execução separada fora do sandbox;
  dentro dele o loop assíncrono ficou aguardando. As chamadas de modelo são simuladas.
- 21 testes específicos do Story Intelligence passaram novamente após a verificação
  final do contexto aprovado e do limite combinado das skills.
- Total de casos distintos aprovados nas duas suítes: 519, sem contar novamente os
  21 casos repetidos na checagem final.
- As nove distribuições ZIP foram verificadas quanto à integridade e presença dos
  módulos novos. Nenhuma inclui storage, .venv ou config.toml real.


## Validação desta revisão GPT

- 129 testes passaram e 1 foi ignorado. Foram mantidos os testes existentes de
  Story Intelligence, Skills, capítulos e roteiro, com a configuração isolada para
  impedir chamadas pagas acidentais nos casos locais.
- A integração simulada passa pelo adaptador OpenAI real do MPT, substituindo só
  o cliente SDK remoto: verifica o modelo, regras, memória, fontes, escolha própria
  de motor, timeout, ausência de retries e ausência de geração de mídia.
- Há testes de alegações/inferências/fatos/lacunas, descarte de citações inválidas,
  aprovação manual, persistência antiga e fallback explícito pela interface.
- O teste real foi selecionado nesta entrega, mas ignorado porque não há chave/modelo
  OpenAI configurados neste ambiente. Nenhuma requisição real OpenAI foi enviada;
  respostas simuladas não comprovam qualidade factual de um modelo real.

Para executar o teste real na instalação com OpenAI configurada:

```powershell
$env:MPT_STORY_LIVE_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest -q -rs test/services/test_story_intelligence_gpt.py::test_live_openai_director_when_configured
```

Esse teste envia uma solicitação de planejamento, com duração alvo de cinco minutos,
sem fontes fornecidas: exige indicação de lacunas e não permite aprovação automática.
Pode ter custo de texto. O flag é opt-in para evitar despesas em regressões comuns;
sem configuração válida, o resultado é skipped, não passed.

Nesta revisão foram modificados app/models/story_intelligence.py,
app/services/story_intelligence.py e webui/story_intelligence.py. Foram acrescentados
os testes GPT e atualizados teste local, documentação e pacotes. Não houve alteração
de dependências, configuração real, provedores de mídia ou do formato persistente
obrigatório: novos campos são opcionais ao carregar planos antigos. analysis_revision=2
identifica os novos planos; versões anteriores e snapshots já enviados continuam legíveis.
