# Historical Documentary Director — Angle Intelligence + Fila de Produção

**Versão proposta:** 1.1 | **Destino:** MoneyPrinterTurbo (MPT) / AUTOPILOT | **Escopo:** skill opcional para canais de documentários históricos, reutilizável em qualquer canal que selecione esta skill. **Google Flow fora do escopo.**

## 1. Objetivo

O usuário informa **título, roteiro de referência e opcionalmente até três thumbnails de referência** (o roteiro e as imagens são opcionais quando o título e a pesquisa são suficientes). A skill identifica o **tema**, o **ângulo de referência**, o **ângulo central configurado para o canal** e oferece cinco **ângulos narrativos alternativos**, cada qual com título sugerido, questão central, promessa, emoção dominante, framework, diferenciação e conceito visual. A escolha pode ser **automática** ou **manual**. No modo manual é possível marcar **um, dois, três, quatro ou os cinco ângulos**. Cada ângulo selecionado vira um trabalho independente na **fila de produção sequencial**.

A skill é responsável por **pesquisa → roteiro → descrição com referências → tags → briefing de thumbnail**. O AUTOPILOT/orquestrador do MPT consome esses artefatos e, quando habilitado no perfil de canal, aciona narração, materiais, música/SFX, renderização e publicação. Não confundir especificação desejada com funcionalidade atualmente implementada.

## 2. Controles independentes

1. **Usar Skill** (`skill_enabled`): ON usa a metodologia selecionada; OFF mantém o comportamento atual do MPT. É independente do tipo de vídeo e preserva as opções existentes.
2. **Recriar ângulo / Angle Intelligence** (`angle_enabled`): ON analisa referência e propõe ângulos alternativos; OFF mantém o ângulo/título dado pelo usuário e vai diretamente à pesquisa e ao roteiro.
3. **Seleção de ângulo** (`angle_selection_mode`): `automatic` ou `manual`, só exibida quando `angle_enabled=true`.
   - **Automática:** avalia e recomenda cinco opções, seleciona automaticamente o melhor **ângulo elegível** e enfileira **um vídeo** por padrão. Opcionalmente `automatic_top_n` pode ser configurado entre 1 e 5 **se o usuário ativar explicitamente** múltiplos vídeos.
   - **Manual:** mostra os cinco ângulos com checkbox individual, comparação e justificativa. Permite selecionar **qualquer subconjunto de 1 a 5**; botão `Selecionar todos os 5`; é obrigatório ao menos um.
4. **Referências visuais** (`thumbnail_reference_enabled`, `thumbnail_reference_files`): carregar **0 a 3 thumbnails de referência** (JPG, PNG ou WebP); análise opcional, com prévia e exclusão. Se OFF, não analisar imagens, mesmo quando anexadas.
5. **Enviar selecionados para a fila** (`queue_selected_angles`): adiciona um trabalho por ângulo aprovado, respeitando a ordem definida pelo usuário, sem repetir trabalhos em cliques ou reinícios.
6. **Publicação automática** (`publish_mode`): `off`, `private`, `scheduled`, `public` (somente quando canal autorizado, direitos de uso e checagens de qualidade habilitados). Não se confunde com a escolha automática de ângulo. As publicações não devem ocorrer se o usuário habilitou apenas geração de pacote.

**Interpretação:** “Ligar/desligar” não pode tornar os modos automático e manual incompatíveis com a fila. O usuário pode desligar a troca de ângulo, sem desativar a skill toda.

## 3. Exemplo da interface no MPT

```text
00 · SKILLS
[✓] Usar Skill: Historical Documentary Director
[✓] Angle Intelligence — propor novos ângulos

Seleção: ( ) Automática   (●) Manual

TÍTULO DE REFERÊNCIA
[The British Planted Fake War Plans on a Dead Man. Hitler Fell for It.]
ROTEIRO DE REFERÊNCIA
[Anexar .txt/.md ou colar texto]
[✓] Analisar thumbnails de referência
THUMBNAILS DE REFERÊNCIA (opcional, máximo 3)
[+ Imagem 1] [+ Imagem 2] [+ Imagem 3] [Ver / remover]

[Analisar referência e gerar 5 ângulos]

[✓] 1. Erro de inteligência — Why German Intelligence Believed ...
[✓] 2. Identidade falsa — The Fake Identity That Fooled ...
[ ] 3. Objeto misterioso — The Briefcase That ...
[✓] 4. Personagem esquecido — The Forgotten Man ...
[✓] 5. Estratégia militar — How Britain Misled ...

[Selecionar todos os 5] [Limpar seleção] [Reordenar]
[Adicionar 4 vídeos à fila]

FILA — produção SEQUENCIAL
1/4 [ROTEIRO] Erro de inteligência
2/4 [AGUARDANDO] Identidade falsa
3/4 [AGUARDANDO] Personagem esquecido
4/4 [AGUARDANDO] Estratégia militar

[Iniciar fila] [Pausar após etapa] [Retomar] [Cancelar selecionado]
```

O número de itens e o estado são ilustrativos, não uma captura real de função existente.

## 4. Regras de inteligência editorial

**Tema ≠ ângulo do vídeo ≠ ângulo central do canal.** Tema é o assunto. Ângulo é a pergunta/perspectiva específica deste vídeo. Ângulo central é a lente recorrente do canal, configurada no perfil. O mesmo tema pode sustentar cinco abordagens diferentes.

Cada ângulo tem:
- `angle_id` estável e único
- `name` (ex.: “falha de inteligência”)
- `title_en` e `title_pt` para aprovação (publicação somente em inglês quando perfil `en-US`)
- `core_question`, `point_of_view`, `conflict`, `emotional_trigger`, `originality_delta`
- `story_framework` (A–F), `hook_proposal`, `payoff_promise`
- `thumbnail_hook` (objeto principal, texto curto, tensão visual)
- `source_feasibility`, `historical_caveats`, `editorial_score` + justificativa

Gerar ângulos **substantivamente distintos**, não apenas trocar verbos/adjetivos. Preservar fatos; separar alegações, documentos originais e interpretações. Não copiar frases, ordem de cenas ou trechos extensos do roteiro de referência. Não prometer um resultado que as fontes não sustentam. Deduplicar ângulos semanticamente próximos.

Pontuação editorial proposta (ajustável): curiosidade 25, originalidade 25, thumbnail 20, retenção 15, fontes verificáveis 15; gates obrigatórios: adequação ao tema, credibilidade e diferenciação. A pontuação **não é probabilidade de viralização**.

## 5. Fluxo da geração de cada vídeo

1. Congelar `channel_profile`, `reference_id`, `angle_id`, `angle_version` e parâmetros de produção no momento em que entra na fila.
2. Produzir um dossiê de pesquisa **independente por ângulo**, com fontes primárias quando disponíveis, datas, fatos, afirmações contestadas e links verificáveis; usar o roteiro de referência para entendimento, não como fonte factual suficiente.
3. Escolher A–F e produzir um **roteiro original** adequado à promessa, ao idioma e à duração do canal (ex. 20 minutos). Conteúdo sem repetições gratuitas; hook relevante, rehooks, tensões e payoff, conclusão com callback quando apropriado. Nunca fabricar citações ou tornar falsa uma afirmação para defender o título.
4. Gerar descrição de YouTube com **referências completas e verificadas no final**, tags e hashtags pertinentes ao foco narrativo.
5. Gerar briefing de thumbnail **específico do ângulo**: analisar até três referências visuais (se habilitado), definir ideia principal, contraste, texto curto, composição, cores, restrições de veracidade e três prompts originais opcionais. As referências informam a linguagem visual, não são peças a copiar.
6. Validar: alinhamento **título → hook → história → thumbnail**, autenticidade dos fatos, diferenças substantivas com outros ângulos da mesma fila, duração estimada, integridade dos arquivos.
7. Registrar os entregáveis estruturados e enviar ao pipeline de mídia/narração/renderização/publicação se esse modo estiver ativo.

**Entregas mínimas por vídeo:** `research.md`, `script_en.txt`, `description_en.md`, `tags.txt`, `thumbnail_brief.md`, `thumbnail_reference_analysis.json` (se aplicável), `sources.json`, `metadata.json`, `quality_report.json`. Caminho proposto: `tasks/<job_id>/deliverables/` ou padrão equivalente do MPT atual.

## 6. Fila sequencial e recuperação

- Produção de vídeos **um por vez** (`max_active_video_jobs=1`), da pesquisa até finalizar o escopo habilitado do job. Não iniciar o próximo enquanto o atual estiver `running`, `waiting_approval`, `publishing` ou `recovering`.
- Ordem: seleção do usuário por padrão; pode reordenar pendentes; não reordenar o ativo em execução.
- Estados por job: `queued`, `researching`, `scripting`, `metadata`, `thumbnail_brief`, `media`, `rendering`, `quality_check`, `publishing`, `completed`, `paused`, `failed`, `cancelled`.
- Persistir **checkpoints por estágio**, arquivos, parâmetros e erros. Após reinício: reabrir o mesmo trabalho no estágio faltante (sem informar ID manualmente).
- Gerar `batch_id`, `job_id`, `angle_id` e chave de idempotência por vídeo. Ao clicar novamente em “Adicionar à fila”, **não criar duplicatas** dos mesmos `batch_id + angle_id` sem nova versão explícita.
- Política configurável quando um job falhar: **pausar fila** (mais seguro, padrão) ou **pular para o próximo** após registrar falha. Retry com limites; não publicar, cobrar, gerar ou postar duas vezes por causa de falha de comunicação.
- `pause` atua em pontos seguros entre etapas; permitir `cancel` do job pendente, e cancelamento cooperativo do atual quando suportado. Cancelar não significa que requisição externa já aceita poderá ser desfeita.
- Publicação pública deve depender de autenticação do canal, direitos, verificação de qualidade, configuração explícita e idempotência de envio. Diferenciar envio privado de publicação pública. Se publicação falhar, preservar o resultado e o ID remoto, não enviar novamente sem consulta ao estado.
- Para múltiplos vídeos sobre o **mesmo tema**, exigir **diferenciação editorial mensurável** (pergunta central, desenvolvimento, narrativa, thumbnail e valor informacional). Alertar sobre risco de vídeos muito semelhantes e permitir agendamento escalonado, sem inventar intervalo ideal.
- Progresso da fila: item atual, fase, tempo decorrido, falhas, restante, caminho dos artefatos e URL da publicação quando disponível.

## 7. Exemplo de parâmetros (formato sugerido; não existente no MPT hoje)

```json
{
  "skill_enabled": true,
  "skill_id": "historical_documentary_director",
  "angle_enabled": true,
  "angle_selection_mode": "manual",
  "generate_angle_count": 5,
  "thumbnail_reference_enabled": true,
  "thumbnail_reference_ids": ["ref_thumb_01", "ref_thumb_02", "ref_thumb_03"],
  "thumbnail_concepts_per_angle": 3,
  "selected_angle_ids": ["angle_01", "angle_02", "angle_03", "angle_04", "angle_05"],
  "automatic_top_n": 1,
  "queue_selected_angles": true,
  "queue_order": ["angle_01", "angle_02", "angle_03", "angle_04", "angle_05"],
  "max_active_video_jobs": 1,
  "on_job_failure": "pause_queue",
  "channel_profile_id": "beyond_the_archives",
  "narration_language": "en-US",
  "target_duration_minutes": 20,
  "publish_mode": "private"
}
```

Para modo automático padrão: `angle_selection_mode=automatic`, `automatic_top_n=1`, sem seleção manual; enfileirar apenas o vencedor elegível. Para gerar os cinco no automático, o usuário configura explicitamente `automatic_top_n=5`.

## 8. Arquitetura de integração proposta

Módulos conceituais, sujeito à auditoria do MPT local:

- `skills/historical_documentary_director/reference_analyzer.py`
- `skills/historical_documentary_director/angle_intelligence.py`
- `skills/historical_documentary_director/research.py`
- `skills/historical_documentary_director/narrative.py`
- `skills/historical_documentary_director/seo.py`
- `skills/historical_documentary_director/thumbnail_brief.py`
- `app/services/autopilot_queue.py` (ou adaptação do sistema de tarefas existente)
- `app/services/autopilot_checkpoints.py`
- Integração controlada no WebUI (`webui/Main.py`) e nos serviços de tarefas/materiais existentes, **sem duplicar os pipelines**.

Manter o backend atual de roteiro quando skill OFF. Não acoplar a skill a serviços de imagem específicos. **Google Flow removido**; não introduzir provedores não solicitados. Usar as APIs e integrações configuradas no MPT como provedores externos pelo orquestrador.

## 8A. Thumbnail Intelligence com até 3 imagens de referência (NOVO)

**Entrada:** 0–3 thumbnails enviadas pelo usuário, vinculadas ao lote (`batch_id`). As imagens podem ser distintas entre si, inclusive de canais de nichos adjacentes. Exibir preview e permitir adicionar, substituir, remover e desabilitar a análise sem precisar excluir os arquivos.

**Análise visual de cada referência (sem inferir métricas):**
- Identificar **gancho visual**: pergunta despertada, emoção, objeto dominante, rosto/personagem, contraste e tensão.
- Extrair o **padrão composicional**: posição do foco, espaço reservado para tipografia, hierarquia, número de elementos, paleta, iluminação, legibilidade no mobile, símbolos, mapas, setas/círculos quando existirem.
- Identificar texto visível na thumbnail, se legível, e relação com o título. Não afirmar CTR ou resultado viral sem dados concretos.
- Marcar recursos que **podem ser reinterpretados** e recursos **que não devem ser copiados** (layout distintivo, identidade visual, imagens protegidas, marca do concorrente e textos idênticos).

**Síntese cruzada:** com até 3 referências, identificar o mecanismo de curiosidade que elas têm em comum, sem criar uma colagem ou réplica. Relacionar o mecanismo ao **ângulo novo escolhido**. Priorizar a identidade visual configurada para o canal atual. A análise pode sugerir que determinada referência é incompatível com um ângulo e ignorá-la justificadamente.

**Por vídeo/ângulo selecionado, entregar:**
1. `thumbnail_reference_analysis.json`: análise das referências recebidas, limitações, padrões aproveitáveis e incompatibilidades.
2. `thumbnail_brief.md`: promessa visual, objeto dominante, emoção, relação com título e hook, cena-chave histórica verificável, layout recomendado, texto proposto (idealmente 2–5 palavras, quando houver), paleta e contraste, briefing de 3 propostas diferenciadas.
3. `thumbnail_prompts.json` ou seção equivalente no briefing: três prompts originais em inglês, com orientação 16:9, espaço para texto, negativos relevantes e restrições de precisão. O usuário poderá escolher um conceito ou permitir seleção automática conforme perfil do canal.
4. Opcionalmente as imagens finais, **somente por provedores já configurados no MPT**; esta skill produz o briefing e prompts, não presume que o motor de imagem esteja habilitado.

**Regras da fila:** as 0–3 imagens de referência são associadas ao lote. Cada vídeo da fila cria seu **próprio** briefing, coerente com seu ângulo, mesmo que as mesmas referências sejam reutilizadas. Permitir substituição de referências por ângulo **apenas antes de iniciar seu job**, com versionamento. Alterações no lote não mudam jobs já executando. Não usar miniaturas de concorrentes como imagens finais por padrão.

**Validação técnica e privacidade:** limitar tipos a JPG/PNG/WebP e tamanho de arquivo configurável, verificar formato decodificável, dimensões, imagens repetidas por hash, armazenar localmente com nome seguro, expor somente IDs/caminhos internos e descartar metadados desnecessários. Respeitar permissões de uso de arquivos e confirmar limitações quando o analisador visual não estiver disponível. Nunca inventar leitura de texto invisível ou afirmar identidade de pessoa retratada.

**Critérios de aceite específicos:** 0 imagens não bloqueia; 1, 2, 3 funcionam; 4 é impedido; ligar/desligar funciona; 5 ângulos produzem 5 briefings independentes; texto/composição não copiados; estado e referências persistem após reinício; automação de publicação só usa imagem final aprovada pelas verificações de qualidade.

## 9. Testes de aceite obrigatórios

1. `skill_enabled=false`: MPT continua gerando como antes.
2. `angle_enabled=false`: mantém ângulo original e gera pacote de um vídeo.
3. `automatic`: gera cinco propostas, escolhe uma elegível e enfileira um job.
4. `manual`: selecionar **1, 3 ou 5** propostas; fila tem exatamente a quantidade escolhida, na ordem definida.
5. Cinco selecionados resultam em **cinco pesquisas, cinco roteiros, cinco descrições, cinco conjuntos de tags e cinco briefings diferentes**.
6. Com 0, 1, 2 ou 3 thumbnails de referência, o sistema gera briefings coerentes com o novo ângulo, sem duplicar composições e sem bloquear a execução na ausência de imagens. Rejeitar 4+ arquivos com erro claro.
7. Não existem dois jobs ativos ao mesmo tempo; `completed` avança para o próximo.
8. Job falho pausa a fila na política padrão; retomar não reexecuta etapas concluídas.
9. Reinício do MPT preserva status da fila e arquivos, sem necessidade de digitar ID.
10. Clique repetido em Enfileirar não duplica jobs. Publicação não cria vídeo duplicado.
11. Roteiro de referência é analisado, não copiado; argumentos históricos têm rastreabilidade.
12. Sem fontes suficientes, marcar ângulo não elegível ou pedir revisão; nunca inventar fontes.
13. Modos de publicação `off/private/scheduled/public` respeitam permissões e critérios de qualidade.
14. Perfil de canal isolado: definições de *Beyond the Archives* não afetam outros canais.
15. Todos os dados gerados e IDs podem ser exportados; falhas são legíveis na interface.

## 10. Ordem para Codex

1. Inspecionar o clone **local e personalizado** do MPT; mapear geração de roteiro, tarefas, persistência e publicação existentes.
2. Implementar **primeiro** o pipeline de skill com Angle Intelligence e a geração dos cinco pacotes de texto, em teste sem publicação.
3. Implementar interface de toggles, modo automático/manual, seleção múltipla e lista da fila.
4. Conectar à fila sequencial persistente com retry, checkpoints e idempotência.
5. Integrar fases de mídia, áudio, renderização e publicação já existentes, respeitando perfil de canal e testes.
6. Documentar arquivos alterados, testes, configurações novas e limitações verificadas. Não presumir que recursos não testados estão prontos.

**Resultado esperado:** um único título + roteiro de referência pode produzir **um até cinco vídeos originais**, dependendo do modo e da seleção, **um após o outro**, sem exigir a repetição manual da configuração a cada item.
