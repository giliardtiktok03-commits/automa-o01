# BEYOND THE ARCHIVES — STORY INTELLIGENCE v1.0

**Status:** especificação de implementação para Codex; não representa código já instalado.

## 1. Missão

Criar o primeiro módulo editorial da skill **Beyond the Archives — Editorial Director**. Antes de gerar o roteiro, a skill analisa o assunto, compara com o inventário de episódios já publicados, identifica a estrutura narrativa mais adequada e entrega um **Episode Blueprint** verificável. O módulo deve orientar a produção sem transformar todos os vídeos na mesma fórmula.

**Ordem obrigatória:** novo tema → memória editorial → diagnóstico narrativo → plano de pesquisa → escolha de estrutura → blueprint → validação editorial → aprovação para escrever roteiro.

**Fora do escopo desta fase:** APIs de arquivos históricos, busca/download de imagens, TTS, geração de vídeos, thumbnails, envio ao YouTube, alteração de provedores de mídia, reescrita de vídeos já publicados.

## 2. Identidade permanente do canal

- **Canal:** Beyond the Archives.
- **Assuntos:** military history, intelligence, espionage, covert operations, classified programs, Cold War e consequências geopolíticas.
- **Idioma da narração:** inglês americano; tom sóbrio, preciso, investigativo, sem sensacionalismo artificial.
- **Voz editorial desejada:** dry American mid-baritone, Great Lakes accent, measured, unhurried, matter-of-fact (diretriz de narração, não instrução para alegar fatos de áudio não analisados).
- **Duração padrão:** aproximadamente 20 minutos; ~2.600–2.900 palavras em inglês como meta ajustável conforme leitura real e pausas. Exceções são permitidas quando justificadas pelo assunto.
- **Promessa:** explicar o que ocorreu, por que foi relevante, quais obstáculos mudaram o rumo dos acontecimentos, o que sabemos e o que permanece incerto.
- **Não permitido:** inventar documentos, diálogos, motivações ou resultados; apresentar especulação como fato; ocultar informação central para fabricar suspense; enchimento de tempo; repetir o gancho sem acrescentar valor; narrativas que prometem mais do que entregam.
- **Retenção:** abertura que comunica uma questão concreta e intrigante; progressão com obstáculos/decisões/consequências; reengajamento quando surge informação nova (frequentemente a cada ~45–90 segundos, se fizer sentido), sem marcações mecânicas.
- **Fontes:** manter bibliografia, links e suporte de evidências fora do texto de narração; indicar incerteza no roteiro sempre que ela for material.
- **Direção visual:** preferir registros autênticos, fotografia contextualizada, mapas, documentos, cortes de arquivo; nunca fazer reconstrução de IA passar por prova histórica.

## 3. Channel Memory — inventário inicial

Os três temas a seguir **já foram publicados**, conforme informação do proprietário do canal, e não devem ser oferecidos como ideias inéditas:

| ID | Título | Status | Assunto principal | Arquétipo inferido apenas do tema/título |
|---|---|---|---|---|
| bta-001 | The ENTIRE History of the GRU in 20 Minutes | published | Evolução histórica do GRU | Institutional chronology |
| bta-002 | The CIA Built a Mining Ship. It Was Secretly Hunting a Soviet Submarine | published | Project Azorian | Impossible mission / covert engineering |
| bta-003 | The US Planned to Hide Nuclear Missiles Beneath Greenland’s Ice | published | Project Iceworm | Ambitious plan / operational failure |

**Importante:** a classificação acima é uma hipótese editorial baseada nos temas e títulos, **não** prova da estrutura efetivamente usada nos roteiros publicados. Quando roteiros, descrições, URLs e métricas forem disponibilizados, reavaliar por análise do conteúdo real. Não inventar datas de postagem, URLs, desempenho ou fontes.

Armazenar os dados editáveis em `channel_memory/published_videos.json` (ou estrutura equivalente existente no repositório). Campos sugeridos:

```json
{
  "id": "bta-001",
  "title": "The ENTIRE History of the GRU in 20 Minutes",
  "status": "published",
  "primary_subject": "GRU",
  "topic_aliases": ["Main Intelligence Directorate", "Soviet military intelligence"],
  "editorial_angle": "Institutional history",
  "youtube_url": null,
  "published_at": null,
  "script_path": null,
  "performance_metrics": null,
  "notes": "User confirmed published; no script or analytics supplied."
}
```

Suportar `published`, `scheduled`, `in_production`, `planned` e `archived`. Para prevenção de duplicatas, considerar `published`, `scheduled` e `in_production`, e alertar sobre `planned`; não confundir status. Nunca marcar uma ideia como publicada automaticamente.

## 4. Processo decisório da Story Intelligence

### Fase A — Compreender a promessa

Entrada mínima: **tema, título provisório ou pergunta central**. Inputs opcionais: duração alvo, ângulo de interesse, fontes/roteiro já fornecidos, público, restrições. Extrair:

- Objeto central: pessoa, agência, operação, tecnologia, crise ou plano.
- Janela temporal e área geográfica, se conhecidas; caso contrário marcar como `unknown`.
- Pergunta que o espectador espera ver respondida.
- Evento central, consequência e hipótese de interesse (se houver fonte).
- Tipo de evidência necessária (arquivos oficiais, testemunhos, cronologia, dados técnicos, mapas, pesquisas historiográficas).

### Fase B — Verificar novidade e proximidade editorial

Comparar título e tema com o inventário, usando aliases, entidades, eventos, período e promessa narrativa. Classificar:

- `duplicate`: mesmo acontecimento e mesma pergunta/perspectiva principal de um episódio existente. **Bloquear como nova sugestão**; apresentar referência ao vídeo existente.
- `overlap_requires_distinct_angle`: mesmo assunto amplo ou entidade, mas possível abordagem nova. Exigir diferença concreta de evento, pergunta, novos registros ou escopo antes de seguir.
- `related_but_distinct`: mesmo universo (por exemplo Guerra Fria) porém evento central e questão próprios. Permitir.
- `new`: tema/editorial suficientemente distinto. Permitir.
- `insufficient_information`: inventário/entrada insuficientes. Sinalizar lacuna sem inventar.

**Regra:** assuntos relacionados não são proibidos por princípio. Novo episódio sobre uma operação do GRU é viável se não reapresentar a história geral do GRU como conteúdo inédito. Similaridade lexical não equivale a repetição histórica. Em casos de dúvida, propor como diferenciar.

### Fase C — Escolher motor e forma narrativa

Escolher **um motor dominante** e, se necessário, um secundário. Seleção por pertinência causal, não por preferências fixas:

| Arquétipo | Quando usar | Promessa dramática | Risco a evitar |
|---|---|---|---|
| `institutional_chronology` | Evolução de organização ou doutrina por décadas | Como mudou, por quê, com quais consequências | Catálogo de fatos sem causalidade |
| `covert_mission` | Operação com objetivo, execução e obstáculos | Como tentaram fazer e o que aconteceu | Sensacionalismo, cronologia confusa |
| `plan_vs_reality` | Projeto ambicioso com limites técnicos/políticos | O plano, os entraves e o desfecho | Revelar fracasso cedo sem explicar processo |
| `intelligence_mystery` | Fato documentado com interpretações concorrentes | O que os registros comprovam e o que não | Vender hipótese como verdade |
| `decision_chain` | Crise resultante de decisões sucessivas | Qual decisão alterou o próximo passo | Leitura psicológica sem evidência |
| `technology_vs_constraints` | Disputa entre capacidade técnica e logística | Por que tecnologia prometia mais do que entregou | Exposição técnica sem impacto humano |
| `rise_and_fall` | Transformação com ascensão e declínio verificáveis | Por que funcionou e por que deixou de funcionar | Forçar declínio inexistente |

Definir justificativa curta para arquétipo escolhido e por que os outros não são a primeira opção. Combinações são permitidas quando sustentadas pelo assunto. Não determinar clímax ou conclusão antes de conhecer os fatos centrais.

### Fase D — Construir a escada de revelações

Antes do roteiro, construir 5–9 **beats causais** (não são cenas visuais nem cortes obrigatórios), e para cada beat registrar:

- `new_information`: qual conhecimento é apresentado.
- `why_it_matters`: qual consequência ou mudança de entendimento ele produz.
- `open_question`: qual pergunta natural fica em aberto.
- `evidence_needed`: que prova/pesquisa sustenta o ponto.
- `confidence`: `verified` / `supported_but_disputed` / `needs_research` / `unknown`.

Evitar beats que repitam a mesma pergunta com palavras diferentes. Suspense deve surgir dos fatos, e não de frases genéricas como “but what happened next changed everything”. A conclusão deve responder ao título e deixar o espectador com uma consequência histórica real.

### Fase E — Criar plano de pesquisa e controle de fontes

Para cada afirmação-chave ou beat de alto impacto, registrar fonte ou tarefa de verificação. Diferenciar:

1. **Fato documentado:** fonte identificável com afirmação correspondente.
2. **Interpretação debatida:** fontes e perspectivas relevantes, com atribuição.
3. **Hipótese plausível não confirmada:** não narrar como fato.
4. **Informação desconhecida:** não preencher com ficção.

Uma saída pode ser preparada com `research_status=needs_research`; **não** rotulá-la como script historicamente validado. O Codex pode conectar pesquisas futuras, mas não deve citar URLs ou documentos inexistentes.

### Fase F — Revisão editorial e entrega

O Episode Blueprint deve ser aprovado nestes critérios:

- Existe uma promessa específica que o episódio realmente pode cumprir?
- O tema não duplica conteúdo publicado?
- O motor narrativo é adequado aos acontecimentos?
- Os beats causais produzem informação nova?
- Onde há incerteza relevante, ela aparece explicitamente?
- Os momentos de reengajamento têm conteúdo, não apenas efeito retórico?
- O final responde à questão principal?
- A duração planejada é compatível com a densidade de fatos e o material disponível?

Se falhar, devolver `needs_revision` com razões e correções concretas. Se houver fato central não verificado, devolver `research_required` e impedir a etiqueta `ready_to_write` até haver suporte suficiente. Não bloquear exploração e rascunhos provisórios, apenas impedir que sejam apresentados como historicamente validados.

## 5. Contrato de saída — Episode Blueprint

Entregar um objeto de dados estruturado e uma visualização legível. Esquema mínimo sugerido:

```json
{
  "project": "Beyond the Archives",
  "module_version": "story_intelligence_v1",
  "input_topic": "Operation Gold: The Spy Tunnel Beneath Berlin",
  "title_working": "Operation Gold: The Spy Tunnel Beneath Berlin",
  "subject": "Operation Gold",
  "editorial_memory_check": {
    "status": "related_but_distinct",
    "matched_video_ids": ["bta-001", "bta-002"],
    "explanation": "Intelligence/Cold War overlap, but a distinct operation and central question."
  },
  "primary_story_engine": "covert_mission",
  "secondary_story_engine": "intelligence_mystery",
  "reason_for_structure": "A defined covert objective, technical execution and questions about operational compromise.",
  "core_question": "What did the tunnel operation achieve, and how was it compromised?",
  "title_promise": "Explain the tunnel operation, its operational outcome and competing explanations with sources.",
  "target_duration_minutes": 20,
  "target_word_count_range": [2600, 2900],
  "opening_hook_strategy": "Start from an independently verifiable consequence or dilemma, not an invented scene.",
  "narrative_beats": [],
  "research_questions": [
    "Which sources establish the participants, dates and objectives?",
    "What information was obtained, according to reliable records?",
    "What evidence supports accounts of compromise and its timing?"
  ],
  "source_register": [],
  "visual_evidence_ideas": ["Period maps", "Declassified records", "Contemporary photographs"],
  "risk_flags": ["Do not assert contested details without attribution."],
  "readiness": "research_required",
  "revision_notes": []
}
```

**Atenção:** o objeto acima é **exemplo de formato**, não um resultado de pesquisa factual sobre Operation Gold; os beats e fontes permanecem vazios deliberadamente até verificação. Identificadores correspondentes indicam afinidade temática, não duplicação.

## 6. Interação com o MPT

- A skill editorial será um módulo **independente da geração de mídia**, acionado antes de criar roteiro.
- Deve poder ser executada em modo de **diagnóstico/blueprint apenas**, sem iniciar `task.py` ou geração de vídeo.
- Ao autorizar roteiro, transmitir ao gerador de texto o blueprint e as regras editoriais, nunca confundir instruções com texto falado.
- O gerador escreve **em inglês** e preserva fatos/ressalvas e a promessa editorial.
- Se o projeto já possuir mecanismos equivalentes, integrar sem criar estruturas redundantes; inspecionar o repositório antes de modificar arquivos.
- Usar persistência simples compatível com estrutura atual (`JSON`/`SQLite` se apropriado); evitar dependências desnecessárias.
- Manter o comportamento existente do MPT quando a nova skill estiver desligada.
- Não integrar automaticamente com imagens, arquivos ou APIs neste módulo.

### Fluxo de interface proposto

1. Campo **Topic or Working Title**.
2. Botão **Analyze Story**.
3. Aba **Channel Memory**: episódio semelhante, classificação e justificativa.
4. Aba **Narrative Strategy**: motor primário/secundário, questão central e justificativa.
5. Aba **Research & Evidence**: fontes registradas, lacunas e riscos.
6. Aba **Episode Blueprint**: beats revisáveis, estado e ação **Approve for Script** quando habilitada.
7. Botão opcional **Save to Editorial Library** com status `planned` ou `in_production`; **nunca** mudar para `published` sem confirmação.

## 7. Testes de aceitação

Executar verificações automáticas e/ou manuais com saída auditável:

| Entrada | Comportamento esperado |
|---|---|
| `The ENTIRE History of the GRU in 20 Minutes` | Detecta duplicata com `bta-001`; não sugere como estreia. |
| `Project Azorian: The CIA's Mining Ship` | Detecta duplicata temática e promessa central próxima a `bta-002`. |
| `The US Planned to Hide Nuclear Missiles Beneath Greenland’s Ice` | Detecta duplicata com `bta-003`. |
| `Operation Gold: The Spy Tunnel Beneath Berlin` | `related_but_distinct` ou `new` conforme os dados disponíveis; sugere `covert_mission` com necessidade de pesquisa, sem afirmar fatos sem fontes. |
| `A Specific GRU Operation Not Covered in the Published GRU Episode` | `overlap_requires_distinct_angle` até confirmar o evento específico e ângulo novo; não bloquear automaticamente só pela sigla GRU. |
| Tema sem fontes | Gera estratégia provisória, `research_required`, sem inventar citações. |
| Tema com documentos contraditórios | Registra versões e sinaliza controvérsia; não apresenta apenas uma como certeza. |
| Skill desligada | MPT se comporta como antes, sem alteração de pipeline. |

### Indicadores de qualidade

Não usar uma pontuação numérica arbitrária como substituto do julgamento editorial. Registrar justificativas específicas: novidade, causalidade, promessa, evidência, densidade e adequação do motor narrativo. Guardar versão do blueprint para comparação de revisões.

## 8. Prompt mestre para o agente Story Intelligence

> You are the **Story Intelligence Director** for *Beyond the Archives*, an English-language historical documentary channel focused on military history, espionage, intelligence and covert operations. Your task is to diagnose and plan, **not yet write the full script**.
>
> First compare the proposed topic with the channel's published, scheduled and in-production episodes. Distinguish true duplicates from related but genuinely new stories. Never recommend a published video as a new idea.
>
> Identify the actual central historical question and the narrative engine that best fits the evidence: institutional chronology, covert mission, plan versus reality, intelligence mystery, decision chain, technology versus constraints or rise and fall. Do not force all episodes into the same arc.
>
> Produce a compelling but accurate title promise, a proposed hook strategy, 5–9 causally advancing narrative beats when sufficient information exists, a research checklist, source requirements, caveats, a suggested duration and visual evidence ideas. Mark anything unverified as needing research and never invent events, quotes, sources, dates, dialogue or motives. Treat competing interpretations fairly.
>
> Build genuine curiosity through meaningful information rather than artificial cliffhangers. Protect the viewer's trust by answering the question promised in the title. Avoid filler, mechanical rehooks, and repeated facts. A documentary plan is not historically verified until its key claims have identifiable support.
>
> Output both a machine-readable Episode Blueprint and a concise editorial report. Write interface explanations in Portuguese if the app is localized in Portuguese, but titles, narration samples and episode creative content in natural American English.

## 9. Instrução de execução para Codex

1. Inspecione a estrutura atual do projeto MPT, inclusive a skill editorial unificada existente, antes de codificar.
2. Não duplique contratos, modelos ou telas já presentes; reutilize sempre que viável.
3. Implemente `Channel Memory` inicial com os três episódios marcados como publicados, sem preencher metadados desconhecidos.
4. Implemente um serviço de `Story Intelligence` que aceite tema e inventário, classifique novidade, proponha motor narrativo e devolva `Episode Blueprint` com justificativas e lacunas factuais.
5. Integre um modo de teste isolado sem geração de vídeo; exponha resultados para revisão humana.
6. Garanta que a função seja opcional e retrocompatível; a integração com o gerador de roteiro deve ocorrer apenas quando ativada.
7. Crie testes automatizados equivalentes aos casos da seção 7, especialmente bloqueio de duplicações e não invenção de fontes.
8. Mostre quais arquivos foram criados/modificados, como executar os testes e uma saída de teste real. Não declarar testes aprovados sem executá-los.

## 10. Critério de conclusão desta fase

Considerar esta versão concluída quando o usuário conseguir informar um tema, receber um relatório editorial distinto, detectar temas publicados, escolher/revisar a estrutura narrativa, consultar lacunas de pesquisa e salvar o blueprint — sem gerar áudio ou vídeo e sem efeitos colaterais sobre o MPT existente.
