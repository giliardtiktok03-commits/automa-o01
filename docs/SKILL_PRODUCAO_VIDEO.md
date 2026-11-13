# Historical Documentary Director — narração e vídeo

Esta fase conecta os pacotes editoriais aprovados à narração e à montagem existentes do MPT. A publicação permanece desligada. Não há novo provedor de voz, imagem, música ou publicação.

## Configurar no bloco da Skill

1. Ative Historical Documentary Director no bloco **00 · Configurações de Skills** e escolha o canal em **00.1**.
2. Em **00.4 · Pesquisa e revisão**, abra **Produção · narração, imagens, legendas e música**.
3. Escolha a entrega: **Somente pacote editorial** (padrão compatível com lotes anteriores), **Pacote + narração** ou **Pacote + narração + vídeo completo**.
4. Informe o identificador exato de uma voz já configurada no MPT. O padrão `en-US-ChristopherNeural-Male` é uma voz em inglês. Ajuste-o ao idioma do canal. Para legendas, Edge aproveita a temporização da voz; provedores sem temporização precisam de Whisper configurado.
5. Para vídeo, escolha bancos + DeepInfra ou somente DeepInfra. O padrão de imagem é **PrunaAI P-Image**, ID `PrunaAI/p-image`. Há controle total por vídeo de 0–120 solicitações e opção explícita **sem limite**. Sem limite pode consumir saldo para todas as cenas. Os bancos continuam sujeitos à validação visual existente; rejeições seguem o fluxo de imagem existente.
6. Ative/desative legendas e música local. Música ativada exige biblioteca local preenchida. Selecione uma fonte instalada no MPT. Formato do vídeo: **16:9**.
7. Salve as preferências e envie um novo lote. Cada ângulo selecionado gera um pacote independente e, conforme a opção congelada no envio, sua própria narração/vídeo. A fila continua sequencial, um item de cada vez.

Preferências são independentes por canal, persistidas em `director_profiles` no SQLite existente. O `Request.production` é copiado para cada lote/item. Alterações não modificam lotes já enviados. Não se guardam chaves no novo contrato. A configuração e autenticação existentes são usadas em memória sob o mesmo bloqueio do gerador manual. O provedor/modelo de texto congelados no pacote também são usados no planejamento de cenas. O catálogo e os provedores manuais não foram alterados.

## Etapas e recuperação

O roteiro revisado é passado diretamente ao TTS, sem regeneração de roteiro. O job editorial mantém o mesmo UUID em `storage/tasks/<ID>` para todos os arquivos.

- `director_narration`: chamada remota explícita, grava `script.json`, `audio.mp3` e, quando habilitado, `subtitle.srt`; registra tamanho e SHA-256 dos arquivos e duração real do áudio.
- `director_video`: reutiliza `mixed_resume.run`, incluindo o primeiro planejamento, as cenas, os registros de solicitações de imagens e a montagem existentes. É uma etapa recuperável localmente; uma interrupção do processo durante a montagem reaproveita áudio e cenas salvos.
- `director_media_export`: acrescenta `media_report.json` ao ZIP editorial. Áudio e vídeo ficam na pasta da tarefa; não são copiados para o ZIP para evitar duplicar arquivos grandes.

Se o computador reiniciar, abra novamente o MPT e mantenha a execução da fila ativa. O SQLite reencontra a tarefa no mesmo ID. Um resultado remoto desconhecido da narração bloqueia a fila para revisão; não há reenvio automático. Use a autorização de nova tentativa já existente somente após revisar o provedor. Falhas normais pausam a fila conforme a política escolhida; a retomada explícita preserva etapas concluídas. Resultados desconhecidos do DeepInfra continuam protegidos pelos registros de imagens existentes. Não apague `storage`, áudio, legendas ou manifestos.

Pausar/cancelar é cooperativo entre etapas: uma chamada em curso ou a etapa de montagem já iniciada termina antes de o controle ser aplicado. Esta fase não introduz interrupção no meio de uma solicitação remota ou de um quadro renderizado.

Se um arquivo de narração/legenda mudou, o hash impede o uso silencioso. Se o processo morreu após salvar `final-1.mp4`, a retomada confere a saída antes de anunciar conclusão e não solicita novas cenas. Nenhuma dessas rotas chama o publicador.

## Verificação e entrega

O relatório editorial mantém o escopo de pesquisa/roteiro/metadata/briefings. A aprovação editorial automática é pré-requisito para qualquer geração de mídia.

A verificação técnica do vídeo exige saída não vazia, duração compatível com o plano de cenas, decodificação FFmpeg de áudio/vídeo completos, proporção 16:9 e duração de áudio/vídeo compatível com a narração (tolerância de um segundo). Registra tamanho, hash, dimensões e duração. Essa verificação não substitui revisão histórica de cada cena, avaliação humana da voz ou direitos de publicação.

Na fila da Skill, o pacote continua disponível para download. **Mostrar prévia da mídia** abre o áudio/vídeo concluído e informa a pasta. O resultado JSON contém os recibos de mídia; `published` e `publish_allowed` continuam falsos. Só se marca `video_generated` quando a montagem e a verificação técnica terminam.

## Limites desta fase

Não gera efeitos sonoros, thumbnail final ou música por IA. Mantém os três briefings/prompts de thumbnail e oferece a biblioteca de música existente. A narração é necessária para a montagem nesta fase; escolha somente pacote editorial para desativá-la. Não configura YouTube, não publica e não inclui Google Flow. O modo manual, os modelos DeepInfra anteriores e as integrações de bancos permanecem disponíveis.

## Arquivos

- `app/models/historical_director.py`: opções tipadas sem credenciais; padrão editorial.
- `app/services/historical_director/production.py`: ponte após revisão e relatório de mídia.
- `app/services/historical_director/video_production.py`: parâmetros congelados, TTS existente, montagem/retomada e verificação.
- `app/services/historical_director/repository.py`: preserva a identidade de lotes editoriais anteriores ao novo campo opcional, sem migração de banco.
- `webui/historical_director.py`: opções e prévias dentro do bloco da Skill.
- `test/services/test_historical_director_video.py`, `test/services/test_skill_workspace.py`: recuperação, compatibilidade e interface.

## Validação

Testes automatizados sem chamadas pagas: contrato e padrões, isolamento/restauração de configurações, roteiro/voz/modelo congelados, narração real sintética codificada por FFmpeg, reutilização após reabrir o SQLite, alteração de arquivo bloqueada, chamada remota interrompida sem reenvio, repetição de montagem sem repetir TTS, recuperação após salvar saída final, verificação real de vídeo/áudio, montagem real do MPT com entradas sintéticas, preflight antes de TTS, identidade de lotes legados e configuração persistida na interface por canal. Regressão inclui pesquisa/ângulos/pacotes/fila, AUTOPILOT, retomada mista, DeepInfra e validação visual.

A geração real com sua voz/API e um documentário completo deve ser conferida no Windows; não há chaves de API neste ambiente. O teste de P-Image anteriormente realizado por você continua sendo a evidência da integração real de imagens.

Resultado da bateria desta fase: **233 testes passaram e 1 foi ignorado**, incluindo as regressões citadas acima. O teste ignorado mantém a condição existente da suíte. Os avisos observados são de depreciação do NumPy/MoviePy. Verificação adicional em Chromium/Playwright: opções visíveis no bloco da Skill, modo vídeo, alteração de “sem limite” e salvamento de preferências por canal; nenhuma exceção de interface e nenhuma chamada paga.
