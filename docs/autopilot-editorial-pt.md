# AUTOPILOT — etapa 2: título, fontes e roteiro com as Skills existentes

Esta atualização acrescenta a produção editorial de um vídeo novo ao cadastro de
canais e à recuperação da etapa 1. Reutiliza a biblioteca e o painel **00 ·
Configurações de Skills**, os adaptadores de texto do MPT e o Story Intelligence.
Não é necessário instalar uma segunda biblioteca de Skills.

## Instalação e uso no Windows

1. Feche o servidor do MPT. Faça backup do código, de `config.toml` e de `storage`
   com o programa fechado. Mescle os arquivos do ZIP na raiz do MPT, substituindo
   os arquivos de código correspondentes. O ZIP não contém configurações,
   credenciais, banco de tarefas nem vídeos e inclui os arquivos da etapa 1.
2. Reabra o MPT. No painel 00, ative as Skills editoriais e escolha as Skills
   na ordem desejada: a primeira tem prioridade. Use **Instalar ou gerenciar
   SKILL.md** para administrar os mesmos arquivos já existentes.
3. No AUTOPILOT, selecione seu canal ou cadastre um. O identificador é interno,
   sem `@` (por exemplo `beyondthearchives-v2b`). Marque **Salvar neste canal a
   seleção do painel 00 · Configurações de Skills** e salve o canal.
4. Configure idioma, nicho, duração, modelo de pesquisa e provedor de roteiro.
   Autorize pesquisa e roteiro automáticos para o canal. Os domínios opcionais
   restringem a busca: informe pelo menos dois domínios para permitir duas fontes
   independentes. Deixe vazio para busca sem essa restrição.
5. A pesquisa exige uma chave da **API oficial OpenAI** configurada no MPT
   (`openai_api_key`) ou `OPENAI_API_KEY`. Endereço oficial:
   `https://api.openai.com/v1`. Login ChatGPT/Codex para texto não substitui essa
   chave. O roteiro e as revisões usam o provedor de texto escolhido, inclusive
   os adaptadores Codex/ChatGPT existentes quando configurados. Acesso a modelos,
   ferramentas, saldo e limites dependem da conta real do usuário.
6. Informe **Título do novo vídeo**, escolha o canal e clique **Pesquisar e gerar
   roteiro**. Ative **Ativar AUTOPILOT**. A seleção de Skills e os modelos são
   congelados no envio; alterações posteriores do painel ou da biblioteca não
   reescrevem uma tarefa já criada. Uma aprovação de Blueprint de outro tema no
   painel manual não é reutilizada: o novo título recebe seu próprio Blueprint.
7. Em **Roteiro pronto**, abra o resultado e baixe o roteiro TXT e o pacote JSON
   com pesquisa, descrição com referências no final, tags, hashtags e briefing
   da thumbnail. Esta etapa produz o briefing, ainda não a imagem da thumbnail.

## Etapas e condições de aprovação

Busca web real pela Responses API → leitura das páginas → correspondência literal
entre trechos e texto baixado → revisão editorial → Blueprint quando exigido →
roteiro → revisão do roteiro → descrição/tags/briefing → revisão do pacote.

São exigidas 2–6 referências em pelo menos dois hosts distintos (isso não garante
independência editorial). Todas devem aparecer nas fontes/citações retornadas
pela ferramenta de busca. Cada afirmação tem trechos de suporte identificados.
O leitor aceita páginas HTTPS públicas de texto/HTML, até 1 MiB por página e 60 mil
caracteres extraídos. PDF, páginas dependentes de JavaScript, bloqueios, paywalls,
redirecionamentos fora dos domínios e trechos não localizados interrompem o fluxo;
não são convertidos silenciosamente em pesquisa aprovada.

A Skill Beyond the Archives mantém os gates existentes. Seu Blueprint passa por
uma chamada crítica adicional que deve confirmar explicitamente todos os beats.
Somente então o orquestrador marca o suporte revisado, pede aprovação ao módulo
existente e vincula uma cópia do Blueprint à Skill congelada. Isso é revisão
**automática**, identificada como tal no resultado; não simula aprovação humana.
O modelo que gera o Blueprint continua sem poder se aprovar sozinho. O fluxo
manual de Story Intelligence continua com seu procedimento anterior.

As revisões por IA e a correspondência textual são filtros, não prova de verdade
histórica nem substituto de revisão especializada. Não há promessa de roteiro
válido para qualquer título: falta de evidência, contradições, memória de tema
repetido ou duração incompatível bloqueiam a tarefa. A contagem de palavras usa
limites aproximados, especialmente inadequados a idiomas sem separação por espaços.

## Retomada, duplicidade e custos

O SQLite migra de versão 1 para 2 acrescentando tabelas editoriais. Canais antigos,
projetos de recuperação, configurações e vídeos são preservados. Canais antigos
começam com geração editorial desativada. O estado geral salvo do worker continua
controlando a recuperação autorizada; geração nova exige autorização do canal.

Cada etapa tem intenção persistida antes da chamada e artefato com hash depois da
conclusão. Ao reabrir o MPT, o worker reutiliza etapas concluídas e retoma operações
locais seguras. Se o processo caiu durante uma chamada remota, não é possível
saber se houve cobrança/resultado: a tarefa fica bloqueada sem reenviar a chamada
por conta própria. O usuário pode autorizar **Repetir etapa pendente** ou refazer
toda a pesquisa; as etapas antigas são arquivadas no histórico SQLite. Uma nova
chamada pode ser cobrada. Não é garantia de execução exatamente uma vez na API.

Mesmo canal + mesmo título normalizado retornam a tarefa existente, inclusive
quando concluída. Há lock entre processos para execução serial. A comparação não
é detecção semântica geral de assuntos semelhantes; Beyond the Archives também
reutiliza sua memória editorial existente. Nesta etapa não se adicionam episódios
como publicados à memória: não houve publicação.

Há limites de fontes, duração, tamanho de entrada/saída da pesquisa e tentativas
sem repetição automática. Não há teto monetário por tarefa nem estimativa de valor
confiável. Pesquisa, texto, revisões e Blueprint podem consumir saldo conforme o
provedor. Preços e limites devem ser conferidos no painel da conta. Nenhuma chamada
paga foi executada na validação desta atualização.

## Escopo preservado e próximo passo

A recuperação de projetos mistos e a opção DeepInfra sem limite de quantidade
continuam disponíveis. Roteiro, narração, Skills e materiais antigos não são
substituídos pelo novo perfil. Nenhuma integração existente é removida e Google
Flow não participa do novo fluxo.

O fluxo novo ainda não chama narração, DeepInfra/Pexels/Pixabay para mídia, música,
SFX, legendas, renderização ou publicação. Não produz nem publica um vídeo só com
o título nesta etapa. Esses passos dependem das próximas conexões do orquestrador.

## Validação e referências técnicas

Testes offline cobrem seleção/prioridade de Skills no formulário existente,
congelamento do conteúdo, envio por título/canal, busca e citações simuladas,
rejeição de trechos fabricados, leitura limitada, bloqueio de DNS privado,
revisões, gate do Blueprint, migração do banco, duplicidade, interrupção remota,
reutilização das etapas e preservação da recuperação anterior. A interface completa
foi aberta em Chromium; o formulário e a mensagem de credencial ausente foram
verificados. O teste de API real exige credenciais e é separado e optativo.

Documentação oficial consultada em 11/11/2026:
- https://developers.openai.com/api/docs/guides/tools-web-search
- https://developers.openai.com/api/reference/resources/responses/methods/create
- https://openai.com/api/pricing/

A documentação confirma `web_search`, filtro `allowed_domains` e inclusão de
`web_search_call.action.sources`. Isso verifica o contrato documentado, não a
habilitação nem o saldo da conta local do Windows.
