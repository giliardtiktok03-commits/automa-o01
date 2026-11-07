# AI33.Pro integrado ao MPT

Esta versão substitui a geração sintética OpenAI/ChatGPT, Codex e Flow por
AI33.Pro. Preserva ChatGPT para texto, planejamento de cenas e validação visual;
preserva Pexels, Pixabay, Coverr, áudio externo, vozes, Whisper, legendas,
ritmo de abertura, regras de repetição, renderização, capítulos e fila.
Não adiciona serviços AI33 de áudio nem o sistema de Skills nesta entrega.

## Instalar

1. Pare o MPT com Ctrl+C e encerre qualquer teste de geração no PowerShell.
2. Faça backup da instalação, principalmente `config.toml` e `storage`.
3. Extraia `MPT-AI33-integrado-Windows.zip` na pasta que contém `webui.bat`.
4. Preserve `config.toml`, `storage`, `.venv` e imagens já pagas.
5. Reabra `webui.bat`. Não é necessário instalar novas dependências.

## Configurar pela interface

Em **Configurações do Vídeo → Configurar fontes de material**, localize
**APIs de geração de imagens por IA → AI33.Pro · Imagens IA**.

- Cole a **chave AI33.Pro** no campo protegido. Ela será salva na configuração
  local do MPT; não precisa reconfigurar a variável de ambiente a cada sessão.
- Clique **Conectar e carregar modelos AI33**. Isso consulta o catálogo, sem
  pedir uma imagem. A seleção é baseada nos modelos retornados pela conta.
- Selecione modelo, resolução e qualidade quando o modelo oferecer esses campos.
  Modelos que exigem imagem de referência não aparecem nesta entrega somente texto.
- Defina **Teto da cotação por imagem (créditos AI33)**.
- Selecione a proporção para a cotação e clique **Consultar preço AI33
  (sem gerar imagem)**. A proporção efetiva da produção é a do vídeo.

O teste real do usuário confirmou Seedream 4.5 em 16:9/2K com cotação de
986 créditos naquele momento. Isso não garante preço futuro. O padrão de
1.000 créditos é um limite editável, não uma tarifa. Não se assume que os
créditos equivalem a tokens, reais ou dólares.

A chave continua no `config.toml` local, como os demais serviços. Não é
criptografada por este incremento; mantenha esse arquivo privado. Projetos,
presets, manifests e arquivos de proveniência não recebem a chave.

## Produzir

Em **Fonte do Vídeo**, escolha **Misto: Pexels + Pixabay + Coverr + imagens
AI33**. As quatro fontes podem ser ativadas/desativadas individualmente e
começam ativadas. Apenas bancos com chave e opção ativa são pesquisados.
Quando nenhum clipe aprovado corresponde à cena, usa AI33 dentro dos limites.

ChatGPT/OpenAI continua sendo configurado em **Configurar modelo de IA** para
roteiro, prompts e validação visual. A chave AI33 não substitui essa chave.
A chave OpenAI não é usada para gerar imagens nesta versão.

Também existe **AI33.Pro · Imagens IA** como fonte única. Ela usa o mesmo
planejamento alinhado à narração, com os bancos desativados, e tende a consumir
mais créditos. Ajuste o número máximo de imagens para a quantidade de cenas.
Comece com um vídeo curto e um limite pequeno para conferir o resultado.

Gerar o vídeo pode consumir créditos. A consulta de catálogo/preço não inicia
uma geração. O modo misto mantém o limite de solicitações para o vídeo completo,
inclusive capítulos. O teto de cotação é por imagem. Não há garantia de trava
de preço no servidor; o custo efetivo é registrado quando retornado pela API.

## Retomar e preservar materiais

Cada cena AI33 tem um diretório `mixed/ai33-NNN` com `ai33-image.json` e a
imagem original, além da cópia usada pela montagem. O `task_id` é salvo assim
que recebido. A retomada consulta essa tarefa e recupera o download; não
reinicia o POST pago. Uma solicitação sem resultado/ID confirmado interrompe
o fluxo para revisão. Nunca apague seu checkpoint para contornar isso.

Consultas GET com 429/502/503/504 ou timeout repetem até quatro tentativas.
Se o serviço continuar indisponível, os dados permanecem em disco. Um erro
401 exige verificar chave, conta e saldo; nenhuma geração é repetida para
testar outra chave. Os checkpoints não armazenam a credencial usada: retome
com a mesma conta AI33 que criou a tarefa.

Retomar um projeto misto antigo mantém cenas prontas e imagens pagas com seus
hashes/proveniência originais; novas imagens seguem para AI33. A migração
verifica que roteiro, áudio, edição e fontes de banco continuam iguais.
Guarda assinatura original e identificação da continuação. Projetos por
capítulos verificam também o fingerprint original e preservam backup dos
manifestos antes da migração. Checkpoints antigos sem dados suficientes para
verificar essa correspondência são bloqueados para revisão, sem novas cobranças.

Cards informativos já salvos continuam reutilizáveis. A documentação AI33 não
fornece um código específico verificável de recusa por segurança: erros genéricos
não são tratados como recusa e não causam reformulação, troca de provedor ou
geração de card presumindo o motivo. O fluxo para e mantém o projeto.

Não há inspeção humana automática nem garantia de precisão histórica absoluta.
A validação visual de bancos e o controle editorial existentes continuam ativos.
Imagens geradas são registradas como ilustrações, não como arquivos históricos.

## Rollback

Mantenha backup de código, configuração e storage antes da atualização. Voltar
somente código não desfaz chamadas nem custos. Não exclua tarefas remotas,
imagens ou manifests. Se restaurar a versão anterior, restaure também os
manifestos do backup apropriado sem sobrescrever os resultados novos pagos.
Nenhuma migração de banco de dados nem instalação de dependência é necessária.

## Validação desta entrega

A suíte direcionada cobre contrato AI33, cotação antes do envio, limites por
modelo, retomada sem repetir POST pago, bloqueio das rotas antigas, fontes de
banco, migração de checkpoints, fila, capítulos, validação visual e sanitização
de logs. Inclui renderização real de vídeos curtos nas rotas mista e somente
AI33, usando materiais simulados de cores distintas para verificar ordem e duração.

O componente de configuração foi testado em Chromium com catálogo e cotação
simulados, sem gerar imagens pagas. A interface principal também foi aberta
com AppTest e configuração isolada. A geração real da conta do usuário já
havia funcionado pelo conector isolado; nenhuma nova solicitação paga foi
executada neste ambiente durante a implementação da integração.
