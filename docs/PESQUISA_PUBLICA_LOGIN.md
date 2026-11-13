# Pesquisa pública + ChatGPT/Codex por login

## O que muda

O canal pode escolher entre **API OpenAI com busca web** (padrão anterior) e **Pesquisa pública + ChatGPT/Codex por login**. O novo modo dispensa a chave da API OpenAI na produção editorial: pesquisa/análise, propostas e seleção de ângulos, roteiro, descrição com referências, tags/hashtags, três briefings de thumbnail e Blueprint quando exigido pela Skill. Reutiliza os conectores OAuth existentes; não automatiza cliques no site ChatGPT nem transforma a assinatura em acesso ilimitado.

“Sem API OpenAI” aqui significa sem API key da plataforma OpenAI para esse fluxo editorial. Há consultas HTTP à API pública MediaWiki e ao conector OAuth já instalado. Uso, disponibilidade, elegibilidade de conta/modelo e limites do login continuam sujeitos ao serviço; não há promessa de gratuidade ou disponibilidade ilimitada. Nenhuma autenticação foi contornada e não se adicionou endpoint de login.

## Configurar na Skill

1. Instale esta atualização com o MPT parado, preservando `storage` e `config.toml`.
2. Nas configurações de provedores existentes, conecte **OpenAI - Codex** ou **OpenAI - ChatGPT (Native OAuth)** e configure um modelo disponível para sua conta.
3. Em **00 · Configurações de Skills → Historical Documentary Director → 00.1 → Configurar canal, Skills e autorização → Avançado · modelos e fontes da pesquisa**, escolha:
   - **Modo de pesquisa:** Pesquisa pública + ChatGPT/Codex por login.
   - **Provedor do roteiro:** o mesmo conector OAuth conectado.
   - **Modelo do roteiro:** modelo configurado, ou deixe vazio para herdar o modelo do conector.
4. Salve o canal. O campo **Modelo OpenAI para pesquisa e Blueprint** só vale no modo API.
5. Para o primeiro teste, use **Somente pacote editorial**, uma duração curta compatível com a pesquisa e um ângulo. Mantenha **Analisar thumbnails de referência** desligado.
6. Informe o título, envie a pesquisa e acompanhe as propostas/fila. A seleção continua manual (1–5) ou automática conforme as opções existentes. Modo sem mudança de ângulo mantém o título original.

A autorização e o salvamento não iniciam chamadas por si só. O envio do lote ou a retomada com execução ativa inicia as etapas. Novas preferências valem para novos lotes. Lotes antigos continuam com seu modo congelado. Identidades dos lotes anteriores às novas opções são preservadas; nenhuma migração destrutiva do SQLite é necessária.

## Como a pesquisa funciona

1. O provedor OAuth propõe de uma a três consultas curtas em inglês para o título.
2. O MPT consulta o índice público da Wikipédia em inglês e obtém links externos de até duas páginas por consulta. A Wikipédia serve para descoberta, não para confirmar automaticamente suas próprias referências.
3. O modelo ordena de 2 a 12 IDs de referências efetivamente descobertas. Não pode inventar URLs nessa seleção.
4. O leitor HTTPS existente abre até 12 candidatos e mantém até seis páginas legíveis. Bloqueios, conteúdo não textual, páginas grandes ou sem texto suficiente são registrados como ilegíveis. São necessários dois domínios efetivamente lidos, considerando os destinos dos redirecionamentos.
5. O modelo recebe o texto lido, IDs e URLs e produz o dossiê. Cada afirmação precisa de trecho exato de 20–500 caracteres. O código confere os trechos no texto normalizado, a correspondência de URLs/IDs e as restrições de domínios do canal.
6. As revisões editoriais existentes verificam relevância, suporte à premissa, datas, contradições, duração e coerência. Só então o roteiro e o pacote seguem adiante. Uma validação de citação confirma presença textual; não garante por si só a veracidade de uma página.

O índice inicial é a Wikipédia em inglês e suas referências, não um mecanismo universal de busca da web. Pode funcionar com títulos em outros idiomas porque o modelo propõe consultas em inglês. Temas sem cobertura ou fontes suficientes podem parar com diagnóstico, mesmo que existam páginas úteis fora desse índice. A restrição de domínios vale para as fontes de evidência, não impede a consulta ao índice de descoberta. Não há geração de referências com base somente na memória do modelo.

As requisições públicas usam User-Agent com identificação/contato do projeto, corpo limitado, timeout e `maxlag`. Não são enviados tokens OpenAI aos sites. Não há extração de páginas de resultados comerciais, resolução de CAPTCHA, bypass de login ou fallback automático para pesquisa paga. Uma resposta de limite ou bloqueio interrompe a descoberta para revisão.

## Checkpoints e erros

A pesquisa usa o SQLite existente, com etapas `*_queries`, `*_discovery`, `*_selection`, `*_pages`, `*_dossier` e validação final. O prefixo é `director_research` na análise de referência e `search` na produção de cada ângulo. Consultas, referências, texto lido, hashes e dossiê ficam preservados para auditoria/retomada.

Etapas concluídas são reaproveitadas. Uma chamada remota por login que terminou sem confirmação não é repetida automaticamente; a autorização de tentativa adicional segue o controle existente. A fila continua sequencial. Evidências insuficientes, fontes inventadas e citações ausentes bloqueiam o roteiro. As revisões existentes continuam obrigatórias. Não há troca automática de OAuth para OpenAI com API key.

Diagnósticos comuns:

- **Selecione OpenAI - Codex/ChatGPT:** modo público foi escolhido com um provedor que exige API key.
- **Conecte a conta:** não há autorização salva do conector selecionado.
- **Descoberta indisponível/limitada:** o índice público retornou bloqueio/limite/erro; aguarde e revise.
- **Não foi possível ler dois domínios:** referências não estavam acessíveis ou convergiram no mesmo destino.
- **Pesquisa insuficiente:** o material lido não sustenta o título ou duração; não se preenche com fatos inventados.
- **Citação não aparece na página:** a etapa não segue para narração ou vídeo.

## Limites de outras etapas

- A análise visual de thumbnails de referência ainda usa API OpenAI e é bloqueada ANTES da pesquisa no modo público quando existem imagens para analisar. Desligue essa análise; os três briefings textuais continuam funcionando.
- A validação visual de vídeos dos bancos é uma integração separada e continua usando API OpenAI. Para vídeo sem essa chave, selecione somente imagens DeepInfra e desative a validação visual. A interface mostra esse aviso no modo público. Isso não elimina a própria cobrança do DeepInfra.
- Narração, DeepInfra e outros provedores conservam autenticação e condições de uso existentes. O modo editorial sem API key não os torna gratuitos.
- Música/SFX, thumbnail final e publicação não ganharam novos serviços nesta alteração. A publicação permanece desligada.
- As opções e o comportamento do modo manual e da pesquisa com API foram preservados.

## Arquivos envolvidos

- `app/models/autopilot.py`: `research_backend`, padrão `openai`.
- `app/services/autopilot/public_research.py`: pesquisa pública, seleção e conferência de evidências.
- `app/services/autopilot/editorial.py`: preflight, despacho de pesquisa e Blueprint pelo provedor congelado.
- `app/services/historical_director/runner.py`: pesquisa por referência e proteção da análise visual.
- `app/services/historical_director/repository.py`: compatibilidade das identidades de lotes antigos.
- `app/services/story_intelligence.py`: argumento opcional explícito para Blueprint pelo OAuth; chamadas manuais conservam o padrão OpenAI.
- `webui/historical_director.py`: configurações dentro do bloco da Skill; `webui/autopilot.py` mantém a opção correspondente para canais genéricos.
- Testes de pesquisa pública, Blueprint, interface e identidade de lotes.

## Validação realizada

- **286 testes passaram e 2 foram ignorados** na bateria de regressão, incluindo Skill/ângulos/fila/pacotes, narração/vídeo, AUTOPILOT, Blueprint, DeepInfra, retomada e validação visual. Os dois casos ignorados mantêm condições já existentes das suítes.
- Teste editorial completo sem chave: análise com ângulo original → pesquisa independente de produção → roteiro de 405 palavras → descrição com referências → tags/hashtags → três briefings → exportação. O texto e a rede de pesquisa foram simulados; os caminhos de autenticação e seleção usam os módulos existentes. Nenhum cliente da API OpenAI foi permitido nesse teste.
- Testes dos dois conectores OAuth para Blueprint, sem chave, com o transporte do provedor simulado.
- Testes de retomada após reabrir SQLite, chamada remota interrompida sem reenvio, URLs/citações inventadas, dois domínios reais, fontes ilegíveis, IDs inválidos, limites HTTP e bloqueio de análise visual antes de qualquer chamada paga.
- Teste real de descoberta pública para **Operation Mincemeat** encontrou a página e referências externas. O leitor existente leu **57.155 caracteres** da página da Wikipédia e **4.874 caracteres** da referência no The Guardian. Uma referência da CWGC estava indisponível e não foi tratada como evidência lida. Textos ficam apenas no diagnóstico local; não foram copiados para este documento ou o ZIP.
- O login real do usuário e uma geração com sua conta NÃO foram testados aqui: o ambiente não tem essa autorização. Esse é o teste a executar no Windows. Uma autorização salva também não comprova, sozinha, que o modelo esteja disponível ou que haja cota.

Referências técnicas: [MediaWiki Search](https://www.mediawiki.org/wiki/API:Search), [Extlinks](https://www.mediawiki.org/wiki/API:Extlinks), [API Etiquette](https://www.mediawiki.org/wiki/API:Etiquette), [Wikimedia API Usage Guidelines](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_API_Usage_Guidelines). Respeite as licenças e atribuição das fontes utilizadas; o sistema mantém URLs nas referências e usa trechos curtos de evidência, não copia roteiros concorrentes.

Verificação adicional no navegador Chromium/Playwright: formulário aberto dentro da Skill, modo público e provedor Codex visíveis, salvamento do canal e recarregamento sem exceções. Nenhuma pesquisa ou chamada ao modelo foi iniciada no navegador.
