# Historical Documentary Director — implantação no MPT personalizado

> Layout atualizado: o fluxo agora está integralmente no bloco 00 · Skills.
> Veja `ORGANIZACAO_SKILL_MPT.md` para o cadastro do canal, as seis etapas e os
> controles atuais. As instruções de navegação abaixo descrevem a implantação anterior.

Implementação baseada em `SPEC_HISTORICAL_DOCUMENTARY_DIRECTOR.md`, enviada pelo
usuário, sobre a versão personalizada com AUTOPILOT etapa 2 e DeepInfra sem teto.
Não pressupõe equivalência com o MoneyPrinterTurbo original.

## Diagnóstico e plano apresentado antes das alterações

O painel 00 já instala arquivos declarativos de até 24 KB e congela suas instruções
nos projetos. Um Markdown com requisitos não implementa uploads, botões, análise
visual ou fila. O anexo tem 18.516 bytes, dentro desse limite: sem o diagnóstico
original do Windows não é possível atribuir a falha de instalação ao tamanho.
A implantação fornece uma Skill executável pelo **orquestrador**, sem executar
Markdown como código, e os módulos necessários à experiência solicitada.

Integrações existentes reaproveitadas:
- `webui/channel_skills.py`, `app/services/channel_skills.py` e
  `channel_skill_runtime.py`: biblioteca, seleção opcional, prioridade e snapshots.
- `app/services/autopilot/editorial.py`: busca web real, leitura de fontes,
  conferência dos trechos, revisões, roteiro e metadados.
- `app/services/autopilot/repository.py`: SQLite, checkpoints com hash, histórico
  de tentativas e configuração independente de cada canal.
- `app/services/autopilot/worker.py`: execução sob um único lock entre processos.
- `app/services/story_intelligence.py`: permanece com seus gates quando a Skill
  Beyond the Archives também estiver selecionada. Esta integração não os elimina.
- `app/services/task.py` e `upload_post.py`: identificados como caminhos existentes
  de mídia/publicação, preservados e não acionados pelo novo fluxo editorial.

Fases executadas e validadas em sequência:
1. Pesquisa independente, análise da referência, thumbnails opcionais e cinco
   alternativas revisadas; primeiros 10 testes locais aprovados.
2. Pacotes originais, três conceitos, qualidade e exportação; 16 testes acumulados
   aprovados antes da integração da fila.
3. Integração ao AUTOPILOT com persistência, seleção manual/automática, ordem,
   pausa, cancelamento e retomada; os primeiros 13 testes de fila passaram.
4. Interface completa, regressão e pacote de atualização. As conexões de mídia,
   áudio e publicação são a próxima fase, não recursos declarados como prontos.

## Como instalar e começar

1. Feche o **servidor** do MPT. Faça backup do código, `config.toml` e `storage`
   com o programa fechado. Extraia o ZIP na raiz do MPT, mesclando as pastas e
   substituindo o código correspondente. O ZIP é cumulativo com AUTOPILOT 1/2 e
   DeepInfra; não contém configurações, credenciais, filas reais ou vídeos.
2. Reabra o MPT. No painel **00 · Configurações de Skills**, marque **Ativar
   Skills editoriais** e escolha **Historical Documentary Director**. Ela é
   instalada uma única vez e não ativada automaticamente. Edições próprias e
   arquivamento são respeitados. ID: `historical-documentary-director`.
3. No cadastro do canal no AUTOPILOT, salve a seleção do painel 00. Autorize
   pesquisa/roteiro automáticos e salve idioma, duração e provedor. Se houver
   várias Skills, a primeira continua tendo prioridade.
4. Abra **Historical Documentary Director · Ângulos e fila**, escolha o canal e
   marque **Usar a Skill neste fluxo de documentários**. Informe o título,
   opcionalmente cole um roteiro ou envie TXT/MD em UTF-8. Configure a lente
   recorrente e a identidade visual do canal, separadas do tema deste vídeo.
5. Opcionalmente carregue 0–3 JPG/PNG/WebP e ative a análise visual. O X do
   carregador permite remover/substituir. Com análise desligada, os arquivos
   permanecem anexados ao lote, sem envio ao modelo visual.
6. Se quiser novos ângulos, ative **Angle Intelligence**. Escolha manual ou
   automático. No automático, um pacote é o padrão; 2–5 exigem marcar autorização
   explícita e escolher a quantidade. Pesos editoriais devem somar 100.
7. Clique **Pesquisar referência e analisar ângulos** e ative o AUTOPILOT. Isso
   autoriza chamadas aos provedores configurados, que podem consumir saldo.
8. Manual: examine cinco propostas, títulos EN/PT/local quando aplicável, score,
   fontes, ressalvas e diferenças. Marque de 1 a 5 ângulos elegíveis e defina sua
   ordem. **Selecionar todos os 5** só é habilitado quando os cinco são elegíveis.
   Clique **Adicionar N vídeos à fila**. Automático: o worker enfileira os melhores
   elegíveis; se houver menos que N elegíveis, usa somente os disponíveis. Zero
   elegíveis pausa a fila com explicação.
9. Cada item produz seu próprio pacote, sequencialmente. Quando concluído,
   **Baixar pacote completo (.zip)** reúne os arquivos. Análises e resultados
   também podem ser exportados como JSON com IDs e configuração congelada.

Com mudança de ângulo desligada, mantém o título/ângulo original e cria apenas
um item. Com o novo fluxo desligado, ele não envia novas tarefas. Para desativar
as instruções no **gerador manual** também, desmarque a Skill no painel 00.
Lotes já enviados conservam sua autorização; use Pausar ou Cancelar para pará-los.

## Pesquisa, roteiro e originalidade

A referência é usada para entender tema, perspectiva e estrutura, nunca como prova
factual suficiente. A primeira pesquisa utiliza busca web, requer fontes HTTPS em
pelo menos dois hosts e confere os trechos no texto baixado. Cada ângulo selecionado
faz **nova pesquisa independente**, seguida das revisões existentes do AUTOPILOT.
Não se reutiliza o dossiê inicial como substituto da pesquisa por vídeo.

Cinco propostas têm IDs estáveis, perguntas, perspectivas, conflitos, gatilhos,
frameworks A–F, hooks, promessas, conceitos visuais, fontes e ressalvas. Os pesos
são aplicados pelo código. Uma chamada crítica separada avalia os cinco candidatos
**e todos os dez pares**. Ângulos próximos são excluídos, não forçados à produção.
Scores não são estimativas de viralização. As definições operacionais A–F estão na
Skill instalada e no prompt; não são resultados históricos nem etapas de pesquisa.

O contexto do ângulo é incorporado à cópia congelada da Skill. O original da
biblioteca não é alterado. O título inglês é usado em perfis `en-*`/inglês; o
português, em `pt-*`; outros idiomas exigem `title_local` produzido pela análise.
Idioma/duração são os do canal; o roteiro passa por verificação de extensão
(100–175 palavras por minuto desejado) e revisão do idioma/adequação ao alvo.
Essa aproximação de duração não é uma medição da narração final e tem limitações
em idiomas sem segmentação por espaços.

Há bloqueio de passagens de 18 palavras consecutivas copiadas da referência ou
outros roteiros concluídos do lote. A revisão por IA também compara pergunta,
desenvolvimento, valor informacional, payoff e thumbnail. Isso não é um detector
universal de plágio nem garantia de originalidade semântica. Falhas bloqueiam ou
pausam o trabalho conforme a política escolhida; não são disfarçadas como sucesso.
A revisão é identificada como automática, sem simular aprovação humana.

## Thumbnails de referência e três conceitos por item

O leitor verifica formato real decodificável JPG/PNG/WebP, rejeita animação,
conteúdo inválido, arquivos acima do limite configurado (10 MB por padrão), mais
que 20 megapixels e imagens menores que 64 px. Normaliza orientação, converte
para RGB, limita a 2048 px, remove metadados e usa SHA-256 como nome seguro. Rejeita
imagens repetidas pelo hash do conteúdo normalizado. Não é deduplicação perceptual.

Com análise ligada e imagens presentes, a API de visão recebe somente as cópias
normalizadas e IDs. Extrai mecanismos de curiosidade, composição, hierarquia,
paleta, legibilidade e texto legível, com limitações e proibições de cópia. Não
identifica pessoas nem atribui CTR. Sem imagens, não há chamada de visão.

Cada vídeo cria três conceitos originais com objeto, emoção, relação título/hook,
cena verificável, fontes/afirmações, layout, texto curto, cores, restrições e prompt
original em inglês, 16:9 e espaço para texto. A adaptação das referências é
específica do ângulo e incluída em sua análise exportada. A análise visual básica
do lote é reutilizada, evitando reenviar as mesmas imagens para cada vídeo.

É possível substituir/remover referências de um item **pendente e ainda não
iniciado**. A revisão é incrementada, os arquivos/IDs permanecem locais e o novo
conjunto recebe um checkpoint de análise próprio. Itens ativos ou com checkpoints
não podem trocar de referências. As imagens finais não são geradas nesta fase.

## Fila, pausa, falha e retomada

As tabelas existentes são preservadas; o schema SQLite passa de v1/v2 para **v3**.
Novas tabelas: `director_profiles`, `director_batches`, `director_items`. Jobs e
checkpoints reutilizam `editorial_jobs`, `editorial_stages` e `editorial_history`.
Os IDs de lote, referência, ângulo, revisão e trabalho ficam vinculados. Mesma
solicitação/snapshot retorna o lote existente; repetir o enfileiramento retorna
os mesmos jobs. Para reproduzir deliberadamente um lote, marque a opção de nova
versão explícita antes do envio.

O mesmo lock do AUTOPILOT serializa os processos. A ordem pendente pode mudar;
um item ativo não é movido. Etapas concluídas são reutilizadas. Pausar/cancelar
age em pontos seguros entre etapas, sem prometer desfazer uma requisição externa
já aceita. Uma fila de documentários pausada impede iniciar outro trabalho dessa
fila até ser resolvida; os fluxos antigos de recuperação continuam disponíveis.

Por padrão, falha pausa a fila de documentários. A alternativa **pular** registra
a falha e permite o próximo item. A repetição exige reconhecimento de possível
custo, preserva os checkpoints concluídos e tem limite de três tentativas adicionais
por job. Depois é necessário revisar e criar nova versão explícita. Se o processo
caiu durante uma chamada remota, a retomada **bloqueia sem reenviar automaticamente**:
o sistema não pode saber se houve cobrança/resultado. Não há promessa de execução
exatamente uma vez na API.

**Iniciar fila / Retomar** também ativa o worker global. **Pausar após a etapa
atual** conserva os resultados. **Cancelar item** é cooperativo se ativo.
**Encerrar lote / Cancelar pendentes** libera um lote sem ângulos elegíveis ou com
falhas que o usuário decidiu abandonar, preservando pacotes já concluídos.
Ao reabrir o MPT, tudo vem do disco, sem digitar ID. Após reiniciar o Windows,
ainda é necessário iniciar o servidor do MPT; não foi instalado um serviço do SO.
Para voltar a uma versão antiga do código, restaure também o backup do banco,
pois versões antigas não reconhecem o schema v3.

## Entregáveis e integridade

Pasta: `storage/tasks/<job_id>/deliverables/`:
- `research.md`: resumo, pergunta do ângulo, ressalvas e afirmações/trechos/fontes.
- `script_en.txt`, `description_en.md` para inglês; sufixo `channel` para outros
  idiomas. Referências ficam ao final da descrição.
- `tags.txt`: tags e hashtags.
- `thumbnail_brief.md`, `thumbnail_prompts.json`: três conceitos/prompts por vídeo.
- `thumbnail_reference_analysis.json` quando houve análise visual; inclui adaptação
  específica para o ângulo.
- `sources.json`: referências e recibos locais de leitura, incluindo URL final,
  data e hash quando fornecidos pelo leitor.
- `metadata.json`, `quality_report.json` e `manifest.json` com hashes dos arquivos.

Arquivos são escritos por substituição atômica. Exportar ZIP confere os hashes
persistidos e recusa arquivos alterados. A interrupção durante uma exportação local
pode ser retomada sem novas chamadas pagas. Os JSONs da interface permitem exportar
análise, configuração, Skills derivadas e IDs. Referências de concorrentes não são
incluídas como imagens finais nem publicadas por padrão.

## APIs, custos e limites verificados

Busca e visão usam a **API oficial OpenAI**, por SDK já declarado no projeto,
`https://api.openai.com/v1`. É necessária a chave `openai_api_key` configurada ou
`OPENAI_API_KEY`. Login ChatGPT/Codex do texto é uma credencial separada. Texto e
revisões usam os adaptadores já existentes do provedor salvo no canal. Não há
fallback silencioso de provedor. Modelos precisam suportar a saída estruturada e
a extensão solicitada; limites baixos de saída de certos adaptadores podem bloquear
a tarefa, mesmo quando o provedor funciona para textos curtos.

As chamadas usam limites de tempo e não têm repetição automática. Uma pesquisa
pode consumir várias buscas dentro da mesma resposta, além de tokens. Cinco vídeos
multiplicam pesquisas, roteiros e revisões. Não foi implementado teto monetário por
lote; consulte preço, saldo e limites reais da conta. Todas as validações desta
entrega foram offline/simuladas ou de interface; **nenhuma chamada paga nem teste
ao vivo de geração histórica/visão foi executado**. Disponibilidade do modelo e
habilitação da conta do Windows permanecem por validar no uso real.

O leitor existente aceita HTML/texto HTTPS público, com limites de tamanho,
redirecionamento e DNS; PDF, páginas dependentes de JavaScript, bloqueios e trechos
não localizados podem impedir a pesquisa. Conferir existência/correspondência de
um trecho não autentica o documento nem prova veracidade histórica. Revisões por IA
são filtros; falta de suporte não deve ser preenchida por invenção.

Referências oficiais dos contratos usados:
- https://developers.openai.com/api/docs/guides/tools-web-search
- https://developers.openai.com/api/docs/guides/images-vision
- https://openai.com/api/pricing/

## O que está concluído e o que permanece para a próxima fase

Concluídos: módulos de pesquisa/análise/seleção, controle de ângulo, 0–3 imagens,
modo manual/automático, múltiplos pacotes independentes, perfil isolado por canal,
fila sequencial, persistência, controles e exportações. Skill desligada não envia
trabalhos e o gerador habitual continua disponível. DeepInfra sem teto e integrações
existentes permanecem; Google Flow não é utilizado pelo novo fluxo.

**Não concluídos nesta fase:** narração, SFX, música, mídia, renderização,
thumbnail final, YouTube/OAuth/agendamento e publicação do novo fluxo. Somente
`publish_mode=off` é aceito; `private`, `scheduled` e `public` são rejeitados, não
tratados como configurações funcionais. Não há uploads duplicados porque este fluxo
não realiza upload; idempotência de publicação deverá ser validada na fase própria.
Os estados de mídia/publicação do anexo não são simulados na interface.

## Arquivos relevantes e validação

- `app/models/historical_director.py`: contratos/configurações e saídas.
- `app/services/historical_director/library.py`, `images.py`, `analysis.py`:
  instalação, referências visuais e análise com revisão dos cinco ângulos/dez pares.
- `app/services/historical_director/production.py`, `runner.py`, `repository.py`:
  contexto por vídeo, reutilização editorial, qualidade, exportação e persistência.
- `resource/channel-skills/historical-documentary-director/SKILL.md`: metodologia.
- `webui/historical_director.py`: controles e fila; ligado por `webui/autopilot.py`.
- `webui/channel_skills.py`: disponibiliza a Skill sem ativá-la.
- `app/services/autopilot/repository.py`, `worker.py`: schema v3 e despacho/controlos.
- `test/services/test_historical_director_*.py`: testes por fase.
- `test/services/test_autopilot_editorial.py`: expectativa de schema atualizada para
  v3, mantendo as verificações de preservação dos dados antigos.

Regressão e testes novos: 152 testes aprovados, 6 subtestes, 1 teste de API real
optativo não executado. Cobertura inclui 0/1/2/3 imagens e rejeição de 4, visão
simulada ligada/desligada, seleção 1/3/5 e ordem, automático padrão/5 explícitos,
original sem troca de ângulo, cópia literal, cinco pacotes, exportação íntegra,
concorrência entre workers, queda real de processo sem reenvio remoto, pausa,
limites de retry, cancelamento, versões de referências e isolamento de canais.

Chromium com a interface completa: Skill instalada, seleção dos cinco ângulos,
enfileiramento de cinco itens, pausa persistida e nenhuma exceção na página. O lote
do navegador utilizou análise sintética identificada como demonstração e worker
sem API ativa; não é evidência de qualidade de uma geração histórica ao vivo.
