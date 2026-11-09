# Google Flow global: automação de Chrome experimental

Implementação geral do MPT, sem dependência de skill ou nicho. Flow é uma opção nova e opt-in: Grok, AI33, bancos, áudio, legendas e projetos anteriores permanecem. Não reativa imagens OpenAI/Codex nem Runware para novas solicitações.

## Operação

`Configurar fontes de material → Imagens IA → Google Flow` oferece perfil local, link do projeto, modelo desejado, prazo, custo zero, login e teste isolado. O usuário faz login diretamente no Chrome instalado, em perfil separado, **sem CDP durante o login**. O MPT não coleta senha, códigos, cookies ou tokens.

Depois que o usuário fecha a janela desse perfil, um processo separado abre o Chrome visível com uma porta CDP aleatória, restrita a localhost. Usa Playwright para operar apenas os controles visíveis da página. Não usa endpoints internos ou captura de respostas de rede do Flow, stealth, proxy, troca de contas ou resolução de captcha. O Chrome mantém seu sandbox normal; a produção não usa `--no-sandbox`.

O driver confirma modo imagem, proporção, x1 e modelo desejado. Se configurado para custo zero (padrão), exige a informação visível de custo de 0 créditos antes de enviar. Faz um único clique de envio, compara os resultados visuais com os existentes e só baixa quando há um único resultado novo identificável. Mais de um resultado é tratado como ambiguidade, não como escolha aleatória. Use projeto exclusivo, sem gerações externas em andamento e sem interação manual durante o teste.

A automação é experimental: **não foi validada no site real ou conta do usuário**. Foi validada em Chromium real com HTML simulado. Se a UI real não expuser os controles/estados esperados, a operação para; não há promessa de geração sem supervisão antes desse teste. Modelos listados são preferências, não garantia de disponibilidade na conta.

## Integração ao pipeline

- `google_flow` aparece nas fontes de imagens; modo exclusivo reutiliza pipeline misto, timeline, renderizador e áudio existentes.
- No modo misto, ativa-se o checkbox Flow. Bancos configurados/ativados são consultados primeiro. Flow tem prioridade sobre Grok/AI33 quando explicitamente selecionado. Falha não aciona API paga automaticamente.
- Modo `automatic` é o padrão da nova fonte. `manual_import` e importação de recuperação também estão disponíveis.
- Imagem estática é padrão da fonte exclusiva Flow, com opção de zoom própria, sem mudar a preferência de movimento dos projetos Grok existentes. No modo misto, a preferência de movimento do próprio vídeo permanece respeitada.
- `google_flow.freeze` congela modo, perfil, projeto, modelo, prazo e custo zero; dados não alteram o hash de projetos antigos quando Flow está desativado.
- Os prompts são os mesmos do planejador existente. `google-flow/requests.json` e `flow_prompts.md` exportam cenas ainda candidatas; arquivos sem necessidade não precisam ser gerados manualmente.
- PNGs são validados e normalizados atomicamente; metadados associam cena, hash do pedido, dimensões, checksum e origem ilustrativa. Não são tratados como imagens históricas autênticas.

## Persistência e falhas

Tentativas automáticas ficam em `mixed/google_flow-NNN`: `flow-image.json` contém ID local e fingerprint; `flow-request.json` coordena o processo; `.submitted.json` registra a intenção imediatamente antes do clique; `.result.json` registra o término; `.png` contém o resultado validado. URLs assinadas, cookies e senhas não entram nesses registros.

Arquivo pronto é reutilizado com checksum. Se a tentativa terminou antes do envio, uma retomada explícita pode tentar os controles novamente. Se houve envio ou se o resultado está desconhecido, não reenvia automaticamente. O operador pode baixar a imagem na própria UI Flow e importar pela cena para recuperar, sem nova geração. Não apague marcadores para forçar repetição.

Importação manual sem imagem entra em `TASK_STATE_WAITING`, preservando o projeto. Recusa explícita preserva o comportamento de card editorial. Verificação humana, cota, sessão expirada, erro técnico ou ambiguidade param a operação. Um lock por instalação e outro por perfil impedem disputa interna; não encerram Chrome de outros perfis/programas.

A importação aceita UUID do projeto ou UUID `/chapters/001`, verifica caminhos e não substitui arquivos diferentes já importados. Nomes de upload não definem caminhos de destino. HTML disfarçado de PNG, imagens inválidas e alterações de checksum são rejeitados.

## Dependências e instalação

Playwright é opcional, instalado por `PREPARAR_FLOW_WINDOWS.bat` usando `requirements-flow.txt`. Chrome deve estar instalado pelo usuário. Não é preciso reinstalar Grok ou gerar vídeo para testar uma imagem. Perfis ficam em `storage/flow_browser/profiles`, ignorados pelo Git; o pacote não distribui perfis, configurações ou chaves.

Instruções completas, teste de uma imagem e rollback: `LEIA-ME-FLOW-AUTOMATICO.txt`.

## Validação e pendências

482 testes aprovados, 1 ignorado, na suíte selecionada. Incluem controles reais de Chromium em página simulada, envio único/download, bloqueio de custo positivo, login normal sem porta de automação, resultados desconhecidos sem reenvio, cache de imagens, importação fora de ordem, proteção de caminhos, retomada sem fallback pago, renderização real curta da fonte Flow simulada e regressões de texto/Grok/legendas/fila.

Pendente: teste na conta Google e na versão real da UI Flow do usuário. Não foram testadas gerações reais, latência, cotas, disponibilidade dos modelos ou custo efetivo. Não há rotação automática entre contas nem processamento de cinco pedidos simultâneos. O fluxo precisa parar se o serviço exigir ação humana. A geração continua sujeita às condições e aos controles do Flow.
