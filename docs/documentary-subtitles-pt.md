# Legendas de documentário

Preset explícito em Configurações de Legendas: **Aplicar Montserrat documentário · 60 px**.

Inclui Montserrat ExtraBold, fonte 60, texto branco, contorno preto 4 px, sombra preta suave, centralização horizontal inferior com margem de 5% da altura, sem fundo sólido, exibição por frase e até duas linhas. A fonte vem do [repositório oficial Montserrat](https://github.com/JulietaUla/Montserrat), com a licença OFL incluída.

`subtitle_soft_shadow` e `subtitle_max_lines` ficam desativados por padrão para preservar projetos anteriores. O preset os habilita explicitamente. O limite de linhas divide blocos dentro do intervalo original do SRT, sem perder texto nem modificar o arquivo/narração; a distribuição de tempo entre novos grupos é proporcional ao comprimento do texto, não alinhamento de palavras por ASR.

A ação **Retomar projeto** oferece **Aplicar o estilo atual das legendas ao retomar**, marcada por padrão. O estilo é congelado na submissão, filtrado pela lista de campos permitidos e validado antes da renderização. Isso impede que mudar a UI altere outras tarefas já enfileiradas. Áudio, SRT, imagens e clipes existentes continuam reutilizados. Não afeta geração visual nem a contagem de imagens. Novas cenas ainda necessárias mantêm o fluxo de materiais normal.

Esse override é específico da retomada simples/mista. A retomada de capítulos e vídeos já concluídos não é modificada por essa ação. Projetos sem SRT salvo precisam de uma transcrição antes de ativar legendas; o override não dispara transcrição/gastos automaticamente.

253 testes passaram na suíte selecionada, incluindo fonte real, renderização real de um vídeo com sombra, texto íntegro e grupos de até duas linhas, preset Streamlit, retomada com áudio/clipes salvos, vídeo, materiais e compatibilidade de hashes de projetos antigos. Não foram feitas chamadas pagas reais.

Instalação: `LEIA-ME-LEGENDAS-DOCUMENTARIO.txt`. Faça backup antes de substituir arquivos. Para voltar, feche o MPT e restaure o backup, preservando uma cópia atualizada de storage.
