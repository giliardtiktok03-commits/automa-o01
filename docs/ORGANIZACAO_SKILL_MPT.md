# Historical Documentary Director no bloco da Skill

O fluxo da Historical Documentary Director agora fica integralmente no bloco
**00 · Configurações de Skills**, em largura inteira, antes dos controles de
produção manual. A interface usa as mesmas filas, canais, configurações e tarefas
já existentes; não há migração de banco nesta atualização.

## Organização

| Etapa | Cor | Controles |
| --- | --- | --- |
| 00.1 · Canal e permissões | Azul | Cadastrar/editar canal, idioma, duração, vínculo das Skills e autorização de pesquisa/roteiro |
| 00.2 · Referências | Roxo | Título, roteiro colado/arquivo e até três thumbnails opcionais |
| 00.3 · Ângulos e direção visual | Laranja | Alterar ou manter o ângulo, seleção automática/manual, quantidade e identidade editorial/visual |
| 00.4 · Pesquisa e revisão | Ciano | Análise visual, pesos, política de falha, salvar preferências e iniciar pesquisa |
| 00.5 · Ângulos e seleção | Amarelo | Comparar propostas, selecionar 1–5 ângulos e definir sua ordem |
| 00.6 · Fila e pacotes | Verde | Execução, progresso, pausa, retomada, cancelamento, reordenação e downloads |

Modelos de pesquisa/roteiro e domínios permitidos ficam no avançado do perfil do
canal (00.1). Chaves e autenticações continuam nas configurações globais dos
provedores, compartilhadas pelo MPT; o botão **Configurar acesso aos provedores**
em 00.4 abre diretamente essa configuração. Não foram criadas cópias de chaves
nos perfis ou snapshots da Skill.

A biblioteca **Instalar ou gerenciar SKILL.md** permanece no mesmo bloco 00.
A ativação da Skill é a seleção principal desse bloco; o segundo checkbox
redundante de ativação do fluxo foi removido.

## Como usar

1. Feche o servidor do MPT, faça backup do código, `config.toml` e `storage`, e
   mescle os arquivos do ZIP na raiz do programa. Preserve seus dados.
2. Reabra o MPT. Em 00, ative Skills editoriais e selecione
   **Historical Documentary Director**.
3. Em 00.1, escolha um canal existente ou **Cadastrar novo canal**. No formulário,
   salve as Skills deste bloco e autorize pesquisa/roteiro. Clique
   **Salvar canal desta Skill**. Isso não faz chamadas de geração.
4. Informe referências e opções em 00.2/00.3. Em 00.4, clique
   **Pesquisar referência e analisar ângulos**. Com a autorização válida, o pedido
   é enviado e a execução compartilhada das filas é ativada ali mesmo. Chamadas
   de IA podem consumir saldo. Uma falha no preflight não ativa uma nova pesquisa.
5. Acompanhe as propostas em 00.5 e envie a seleção à fila. No modo automático,
   a seleção segue os critérios já existentes; múltiplos vídeos exigem opt-in.
6. Use 00.6 para acompanhar, pausar, retomar e baixar os pacotes.

Não é necessário abrir AUTOPILOT para cadastrar/autorizar o canal desta Skill nem
para iniciar sua pesquisa. Os novos trabalhos continuam sendo processados pelo
mesmo orquestrador; a organização mudou, sem duplicar a implementação da fila.

## Preservação e compatibilidade

- A seleção das Skills mantém a prioridade original e os projetos continuam com
  suas cópias congeladas. Salvar o canal não reescreve trabalhos já enviados.
- O formulário da Skill preserva opções de recuperação, DeepInfra e demais campos
  salvos do canal. As edições continuam usando controle de versão para detectar
  alterações concorrentes.
- O AUTOPILOT geral não exibe uma segunda cópia do fluxo Historical Documentary
  Director. Para um canal dessa Skill, exibe somente opções de recuperação de
  projetos antigos, preservando suas configurações editoriais.
- O formulário genérico de novo roteiro não oferece canais da Historical
  Documentary Director, evitando desviar do fluxo de referências/ângulos.
- Pacotes do fluxo editorial anterior que já continham essa Skill também são
  exibidos em 00.6, sem duplicar a exibição no AUTOPILOT geral. A listagem consulta
  os últimos 100 trabalhos editoriais; lotes continuam com o limite de exibição
  anterior de 10. Não há remoção de histórico do banco.
- Quando a Skill é desativada, não há formulário de novos pacotes. Seus lotes e
  resultados salvos continuam acessíveis no bloco 00. Desativar a seleção não
  revoga autorizações de trabalhos já enviados: use pausa/cancelamento na fila.
- Há um único interruptor compartilhado de execução. Iniciar uma pesquisa ou
  retomar um lote o ativa; todas as tarefas previamente autorizadas seguem a
  política existente do worker. Pausar um lote age nos pontos seguros já existentes.
- Modo claro, escuro e sistema permanecem disponíveis. Os cabeçalhos das seis
  etapas e os painéis expandidos acompanham a paleta atual.

Os controles de narração, mídia, legendas e produção manual continuam disponíveis
nos módulos existentes. Esta atualização organiza **esta Skill**, sem declarar a
reorganização completa de todos os demais módulos do aplicativo.

## Arquivos alterados

- `webui/Main.py`: coloca o bloco de Skills em largura inteira e coordena o
  controle único da execução com o AUTOPILOT geral.
- `webui/channel_skills.py`: integra o workspace e mantém acesso aos trabalhos
  salvos mesmo com a Skill desativada.
- `webui/historical_director.py`: cadastro/autorização do canal, seis etapas,
  entrada para credenciais, início de pesquisa, seleção e fila no mesmo módulo.
- `webui/autopilot.py`: remove o fluxo duplicado, compartilha o controle de
  execução e roteia resultados anteriores para o bloco correto.
- `webui/appearance.css`: corrige o fundo dos cabeçalhos expandidos no modo escuro.
- `test/services/test_skill_workspace.py`: cobre localização dos controles,
  cadastro/autorização, preservação das configurações/snapshots, início de execução,
  resultados anteriores, Skill desativada e opções de recuperação.

Backend, schema SQLite, pesquisa, fornecedores, processamento e publicação não
foram reimplementados. O escopo continua sendo pacotes editoriais: narração,
mídia, renderização e publicação do fluxo novo ainda não estão conectadas.

## Validação

Regressão selecionada: 161 testes aprovados, um teste opcional de API real não
executado; depois, o conjunto de oito testes do workspace passou, incluindo a
verificação adicional de que opções de recuperação não alteram o perfil da Skill
(162 testes distintos aprovados no total).

Chromium com a interface completa: bloco de Skills com 1280 px em viewport de
1440 px, seis etapas internas, um controle de execução, seleção/envio de cinco
itens e pausa persistida, atalho de credenciais, modo claro/escuro e celular.
O cabeçalho expandido foi conferido na paleta escura. Sem exceções na página.
Os lotes do navegador usaram análise sintética identificada como demonstração,
com worker sem chamadas de API. Nenhuma geração paga foi executada.
