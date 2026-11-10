# Cortes longos, retomada e playlist de música de fundo

## Causa da falha informada

A tarefa de689389-75ed-481d-91a8-ce465beb04a1 falhou em materials com
`Too many shots; enable chapter mode`. O log mostra 0,08 s nessa etapa e nenhuma
chamada ao planejador, aos bancos ou aos geradores de imagens nessa execução.
O áudio externo já havia sido carregado. O erro vinha do limite fixo de 180 cortes,
não da DeepInfra. O projeto Windows não está neste ambiente para inspeção dos arquivos.

## Correção

O planejamento aceita até 720 cortes por execução, divididos em lotes de até 30.
Mantém os IDs globais, a ordem, o texto e os frames. O ritmo não é alongado para
caber no limite: continuam 3 s nos primeiros 30 s, 5 s até 3 min e depois o valor
configurado. Exemplo verificado: 20 minutos com 5 s depois da abertura = 244 cortes.

Cada lote é validado antes de salvar mixed-plan-progress.json. Lotes concluídos
são reaproveitados após interrupção. O modelo recebe o roteiro completo, as unidades
da vez e o último visual anterior para evitar repetição na passagem entre lotes.
As imagens só começam após o plano completo validado. O limite de imagens IA
configurado não foi aumentado nem desativado por esta correção. Acima de 720 cortes,
o modo por capítulos continua necessário.

## Retomar o projeto informado

1. Feche o MPT, faça backup e instale o ZIP na raiz da instalação.
2. Reabra webui.bat e abra **Retomar projeto salvo — modo misto**.
3. Informe de689389-75ed-481d-91a8-ce465beb04a1 e confira o projeto.
4. Use a ação de retomar nesse painel, em vez de criar uma nova geração.

A retomada agora aceita falha anterior à criação de mixed-scenes.json, desde que
o roteiro e o áudio estejam salvos e a pasta mixed não contenha materiais órfãos.
Usa o áudio e o SRT existentes; não gera narração ou transcrição novamente. A prévia
da retomada não faz chamadas à IA. Havendo materiais sem manifesto, interrompe
para evitar novas solicitações que possam duplicar trabalhos já pagos.

## Música de fundo até 200 MB

O limite de cada upload passa a 200 × 1024 × 1024 bytes. Vale na interface e no
serviço que recebe o arquivo, preservando cópia em blocos de 1 MiB, validação real
do áudio, formatos suportados e arquivos temporários/atômicos. A narração mantém
seu limite próprio de 500 MB. Limites dos geradores externos de música não mudaram.

## Playlist

Em **Configurações de Áudio → Fonte da música de fundo → Música de Fundo Personalizada**,
marque **Usar playlist de músicas de fundo**. Adicione entre 1 e 20 arquivos, com
até 200 MB por arquivo. Os formatos são os já aceitos pelo MPT: MP3, M4A, AAC,
WAV, FLAC, OGG, OPUS e WMA.

O campo Ordem das músicas mostra a sequência. Para mover uma faixa ao final,
remova-a da seleção e selecione-a novamente. Você também pode excluir faixas da
playlist por esse campo. A validação é reutilizada entre reruns sem persistir ou
codificar faixas durante o simples preenchimento do painel.

Ao iniciar uma nova produção, as faixas são salvas e concatenadas pelo FFmpeg,
normalizando canais e taxa de amostragem, em um MP3 playlist-<id>.mp3 em storage/bgm.
Um JSON ao lado registra a ordem e os nomes dos arquivos. Os originais são preservados.
O projeto referencia o arquivo combinado pelo mecanismo normal de BGM, sem mudar
provedores. Não há novas dependências ou chamadas pagas para montar a playlist.

As faixas tocam em sequência e a playlist inteira repete quando necessário para
cobrir o vídeo. O volume atual vale para todas. Em capítulos, a playlist usa a
posição global já percorrida, em vez de recomeçar da primeira faixa a cada capítulo.
A retomada de um projeto anterior preserva a música já salva nesse projeto; a
seleção de novos uploads no formulário serve às novas produções.

## Validação

259 testes passaram, 1 foi ignorado e 131 subtestes passaram na regressão conjunta.
Os 14 casos específicos de cortes/retomada/playlist foram conferidos novamente
após a proteção de tempos inválidos e o componente isolado da interface.

Inclui: cobertura exata dos frames em 244 cortes, lotes limitados, IDs e recuperação
de lotes completos, bloqueio de cache alterado, retomada sem gerar áudio, bloqueio
de materiais órfãos, WAV real acima do limite antigo de 30 MB, playlist de faixas
com taxas distintas, ordem conferida pelas frequências reais, interface de múltiplos
arquivos e reordenação sem iniciar codificação, mixagem e renderização FFmpeg existentes.
O teste real DeepInfra foi ignorado por falta de credenciais; esta entrega não
solicitou geração paga de imagens.

## Arquivos

Código: app/services/mixed_materials.py, mixed_resume.py, bgm.py, video.py,
long_form.py; webui/Main.py; novo webui/bgm_playlist.py.
Descrição do endpoint: app/controllers/v1/video.py. Textos do limite em webui/i18n/*.json.
Testes: novos test/services/test_long_shot_planning.py e test_bgm_playlist.py;
alterados test_mixed_resume.py e test_narration_upload.py. Documentação e ZIPs atualizados.

O ZIP não inclui storage, config.toml real ou .venv. Para rollback, feche o MPT e
restaure o código do backup, preservando os arquivos dos projetos e músicas.
