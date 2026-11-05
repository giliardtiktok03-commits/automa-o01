# Vídeos longos com capítulos automáticos

O modo por capítulos cria um vídeo a partir de um tema, sem exigir montagem manual.
O sistema planeja os capítulos, escreve a narração de cada parte, gera voz,
legendas e cenas usando os serviços configurados no MPT e une as partes no final.
Os capítulos são processados sequencialmente para limitar o uso de memória.

## Na interface

1. Configure o provedor de roteiro, a voz e a fonte de imagens/vídeos normalmente.
2. Informe o tema. Deixe o roteiro vazio para geração automática; se já tiver um
   roteiro completo, cole-o no campo de roteiro para que seja dividido em partes.
   O botão tradicional de gerar roteiro continua produzindo o roteiro curto habitual.
3. Abra **Vídeo longo: capítulos automáticos**, ative o modo e escolha a duração
   desejada (1–30 minutos) e a duração aproximada de cada capítulo (1–5 minutos).
4. Selecione **um** vídeo de saída e uma voz de IA ou importe sua narração. Clique em gerar vídeo.

O resultado é um único MP4 com narração, legendas e a música selecionada. A música
é aplicada separadamente em cada capítulo; ainda não há uma faixa contínua ou
transições musicais entre capítulos. A publicação automática nas redes sociais
fica desativada neste modo, inclusive para as partes intermediárias.

A duração é estimada pelo tamanho do roteiro e pela velocidade da voz, não é um
cronômetro exato. Se a soma das partes ultrapassar 30 minutos, a geração para com
uma mensagem de erro e preserva os capítulos, sem cortar a narração no meio.
Nesse caso, use um roteiro menor ou uma meta menor em uma nova tarefa. Para um
limite editorial rígido, deixe uma margem na duração desejada.

## Importar narração de até 500 MB

Em **Configurações de áudio → Enviar narração**, selecione um arquivo MP3, WAV,
M4A, AAC, FLAC ou OGG. O limite é **500 MB por arquivo** (500 × 1024² bytes).
O limite de música de fundo continua em 30 MB. Arquivos grandes são validados
completamente e gravados em blocos de 1 MB, sem uma segunda cópia integral em
memória. O próprio Streamlit mantém o upload original em memória; o computador
precisa de memória e espaço em disco disponíveis. A prévia automática de áudio
é omitida acima de 30 MB para evitar duplicar um arquivo grande no player.

Os iniciadores `mpt webui`, `webui.sh`, `webui.bat` e os comandos Docker foram
ajustados para o novo limite. Reinicie a interface depois da atualização. Se usar
Streamlit diretamente, execute:

```bash
uv run streamlit run webui/Main.py --server.maxUploadSize=501
```

O transporte reserva 1 MB para o envelope do upload; a interface e a validação
continuam limitando o arquivo em si a 500 MB. Um proxy reverso próprio também
precisa aceitar esse tamanho de requisição. Imagens Docker precisam ser
reconstruídas com este código para incluir as novas funções.

### Áudio externo no modo por capítulos

A duração real da gravação define a duração do vídeo; o controle de duração
estimada se aplica somente à narração gerada por IA. A gravação é dividida em
partes sem gerar uma nova voz. O modo por capítulos mantém o limite de 30 minutos
de áudio, independentemente do tamanho do arquivo.

Forneça a transcrição completa no campo de roteiro, ou selecione explicitamente
**Whisper** como provedor de legendas para transcrever cada parte. O Whisper é
obrigatório para legendas da gravação; sem ele, desative as legendas e forneça
a transcrição para orientar a escolha de cenas. Não geramos um roteiro inventado
como substituto do que foi gravado. O Whisper pode precisar baixar um modelo na
primeira utilização e requer recursos de processamento próprios.

Na retomada, reenvie a mesma gravação. Seu conteúdo é comparado por SHA-256,
então mudar apenas o nome do arquivo não invalida os capítulos concluídos.

## Retomar uma falha

O progresso aparece por capítulo, junto com o **ID da tarefa para retomada**.
Copie esse ID para o campo de retomada e gere novamente com os mesmos parâmetros,
arquivos de referência e configurações dos provedores. O roteiro e os capítulos
concluídos permanecem no disco mesmo após reiniciar o servidor. A retomada é
solicitada pelo usuário; não há reenvio automático de operações pagas após falhas.

Os arquivos concluídos são verificados com SHA-256 antes de reutilização. Partes
inexistentes ou alteradas são refeitas. O capítulo que falhou é processado novamente
a partir da sua narração salva, podendo repetir chamadas de voz e imagens; somente
capítulos inteiros concluídos têm reaproveitamento garantido. Uma falha na união
final pode ser retomada sem gerar novamente os capítulos válidos.

O checkpoint compara os parâmetros do vídeo e os áudios de referência. Não
compara mudanças feitas na configuração global dos provedores: mantenha essas
configurações iguais durante uma retomada. Para mudar roteiro, voz ou estilo,
limpe o campo de retomada e crie uma tarefa nova. Não remova os arquivos de
`storage/tasks/<id>/` enquanto quiser preservar a possibilidade de retomada.

## Linha de comando

Depois de instalar com `uv sync --frozen`, por exemplo:

```bash
uv run python cli.py \
  --long-form \
  --video-subject "A história do café no Brasil" \
  --video-language pt-BR \
  --voice-name pt-BR-AntonioNeural-Male \
  --target-duration-minutes 30 \
  --chapter-duration-minutes 3 \
  --video-aspect 16:9 \
  --video-count 1 \
  --task-id 454b96f8-4811-49e3-838e-60574eedc3e8
```

Use um UUID novo para cada projeto. Para retomar, execute o mesmo comando com o
mesmo `--task-id`. A fonte padrão exige as credenciais de banco de vídeos já
previstas pelo MPT. O modo não fornece chaves nem troca os provedores existentes.

A API `POST /api/v1/videos` aceita os campos `long_form: true`,
`target_duration_minutes` e `chapter_duration_minutes`. A retomada está disponível
pela interface e pelo CLI; uma nova chamada de criação à API cria outra tarefa.

## Arquivos e limites atuais

- Vídeo final: `storage/tasks/<id>/final-1.mp4`.
- Plano, roteiros e checksums: `storage/tasks/<id>/chapters.json`.
- Partes: `storage/tasks/<id>/chapters/001/final-1.mp4`, etc.
- Lotes LoomLoom não são suportados neste modo.
- A seleção visual continua dependendo dos provedores existentes e pode repetir
  material se não houver variedade suficiente. A função não garante cenas únicas.
- A retomada usa um bloqueio no disco para impedir duas execuções simultâneas
  sobre o mesmo checkpoint. Os arquivos precisam continuar disponíveis no mesmo
  armazenamento; um checkpoint sozinho não restaura vídeos apagados.

## Validação

```bash
uv run python -m pytest -q test/services/test_long_form.py
```

Os testes de `test_long_form.py` e `test_narration_upload.py` cobrem uploads maiores que 30 MB, limites de tamanho, áudio externo, planejamento, divisão de texto, falhas, retomada após perda do
estado em memória, detecção de arquivos alterados, parâmetros incompatíveis e
união de dois vídeos com áudio usando FFmpeg real. Chamadas pagas de IA são
simuladas nos testes. Um vídeo real de 30 minutos ainda requer validação com os
provedores e recursos de execução escolhidos.
