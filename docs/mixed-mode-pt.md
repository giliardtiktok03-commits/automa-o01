# Modo misto: Pexels + Pixabay + Coverr + imagens IA

O modo misto planeja cenas a partir das passagens da narração. Ele mantém a
sequência e pode combinar vídeos dos bancos com imagens geradas no mesmo
vídeo final. A alternância depende do contexto, não de uma regra mecânica de
uma fonte a cada cena.

## Configuração no Windows

1. Em **Configurar fontes de material**, preencha sua chave do Pexels e sua chave
   do Pixabay e da Coverr, selecionando cada serviço na seção de bancos de vídeo. Basta um
   banco configurado para executar; com mais de um, o modo distribui as buscas e
   tenta a outra fonte quando a primeira não entrega material utilizável.
2. Na seção de imagens, configure **Texto-para-imagem compatível com OpenAI**:
   endereço real da API, modelo disponível na sua conta e chave quando exigida.
   Os textos cinza de exemplo não contam como valores preenchidos.
3. Volte a **Configurações do Vídeo → Fonte do Vídeo** e selecione
   **Misto: Pexels + Pixabay + Coverr + imagens IA**.
4. Escolha o **máximo de imagens IA no vídeo completo** (padrão: 12) e a duração
   desejada de cada cena (padrão: 10 segundos).
5. Mantenha um vídeo por execução. Para este primeiro teste, use o roteiro curto
   já aprovado e mantenha as legendas ativadas para obter tempos mais precisos.
6. Para narração externa, em **Configurações de Legendas → Provedor de legendas**,
   escolha **Whisper — transcrever áudio**. Selecione o modelo **small** para um
   primeiro teste mais leve. O primeiro uso baixa o modelo; se mudar um modelo
   que já estava carregado, reinicie o MPT. Edge usa os tempos da voz gerada e
   não fornece tempos para arquivos de áudio enviados.

O Pixabay já possuía integração no MPT. A mudança permite combiná-lo com Pexels
no mesmo vídeo, em vez de escolher apenas um banco por execução. Configure as
chaves na sua instalação; elas não são enviadas ao repositório.

## Planejamento e sincronização

O modelo de texto configurado para o MPT recebe a narração e unidades
consecutivas do roteiro. Para cada unidade, escolhe banco ou imagem gerada,
descreve época, lugar e contexto e cria uma busca ou prompt específico.

Se houver SRT temporizado da narração, os limites das cenas acompanham seus
marcadores, agrupando falas próximas. Sem SRT válido, os tempos são estimados
pela distribuição do texto e a interface informa essa limitação. Não há garantia
de sincronização exata no modo estimado.

A prioridade é buscar vídeos em Pexels, Pixabay e Coverr, usando somente os
provedores com chave configurada e alternando a primeira fonte entre as cenas.
Uma passagem histórica pode usar detalhes de apoio sem elementos de época —
por exemplo, grãos de café em close. O planejador precisa aprovar explicitamente
essa opção como segura, sem representar pessoas, trabalho, máquinas ou cidades
de outra época. Datas e contexto histórico, por si só, não exigem uma imagem IA.
Quando a cena requer uma reconstituição de época, usa uma ilustração com prompt
específico. Essas imagens não são documentos históricos autênticos.

A meta é usar bancos em pelo menos 75% das cenas, sem impor uma cota rígida.
Se não houver um clipe adequado, o sistema pode gerar uma imagem mesmo acima
dessa proporção, respeitando sempre o limite de solicitações configurado. Nos
capítulos, esse limite continua compartilhado. Inicie uma nova tarefa ao atualizar:
os checkpoints de políticas visuais antigas não são reutilizados.

## Validação visual dos clipes

A opção **Validar clipes visualmente com IA** vem ativada no modo misto. Configure
a chave e URL do **OpenAI** em **Configurar modelo de IA**; essa configuração é
separada da API de geração de imagens. O provedor do roteiro pode continuar sendo
outro. No modo misto, o campo **Modelo com visão** escolhe um modelo compatível com
imagens e Chat Completions JSON; o padrão é `gpt-4.1-mini`, se disponível na conta.
Serviços compatíveis precisam suportar imagens e resposta JSON nesse endpoint.

Para cada candidato baixado, são extraídos três quadros do trecho que será usado,
reduzidos para no máximo 512 pixels. Uma chamada compara os quadros à fala, ao
contexto, à época e ao lugar; aprova somente uma avaliação positiva com confiança
mínima de 0,8. A nota é uma estimativa do modelo, não uma garantia de acerto. Não
aceita analogias visuais que substituam o assunto central, como insetos para
representar exploração humana. A regra é geral, sem depender do nicho do canal.

O padrão permite analisar até três candidatos por cena (ajustável de 1 a 6),
distribuídos entre os bancos disponíveis. As buscas podem usar até duas consultas
alternativas. Avaliações são guardadas em `mixed/visual-checks.json` e reutilizadas
na mesma tarefa quando quadros, passagem, modelo e configuração coincidem.
Amostragem pode perder uma cena inadequada entre os quadros: revise o vídeo final.
Desativar a opção permite usar clipes sem essa verificação.

Se todos os candidatos forem rejeitados ou não houver resultado, há fallback
para imagem gerada, dentro do orçamento disponível e sem consumir verba reservada
às reconstituições planejadas. Se o orçamento não bastar, a tarefa para.
Falhas na análise visual param a tarefa sem aprovação e sem fallback pago. Chamadas
à API de análise têm timeout de 45 segundos e não usam repetição automática.
Análise visual e geração de imagens têm custos separados; a análise acrescenta
tempo. Não há promessa de duração ou de preço por vídeo.

Os logs mostram cena, banco, consulta e aceitação visual. Ao concluir cada plano,
a interface e o log mostram quantas cenas vieram de Pexels, Pixabay, Coverr e IA.
Um banco sem resultados pode terminar com zero cenas. O resumo
`generation_phase_seconds` registra os tempos por fase da execução; a fase de
materiais pode ser subdividida por downloads, inspeção e preparação das cenas.
A composição de legendas do modo misto reutiliza o vídeo como fundo opaco, evitando
uma composição adicional por quadro. O ganho real depende do computador e deve
ser comparado com uma geração equivalente no Windows.

As cenas são renderizadas em sequência, com duração controlada em quadros. O
modo usa cortes simples e velocidade normal para preservar a linha do tempo;
os controles de transição, duração máxima de clipe e velocidade comuns ficam
inativos. A duração de cena do modo misto é a opção relevante. As palavras-chave
globais antigas não são usadas para planejar as cenas desse modo.

## Ritmo variável da abertura

No modo misto, **Ritmo variável na abertura** vem ativado. O mesmo material já
aprovado recebe cortes de enquadramento a cada 3 segundos nos primeiros 30s,
a cada 5 segundos entre 30s e 3 minutos, e depois na duração desejada configurada.
São variações discretas de zoom/recorte (até 8%), não novos arquivos de banco nem
novas imagens geradas. As trocas de assunto/material continuam acompanhando as
unidades da narração: o controle de duração de cena ainda orienta esse planejamento.
Isso evita multiplicar buscas, análises visuais e imagens pagas por corte.

A contagem de fontes continua sendo de materiais/cenas planejadas, não desses
reenquadramentos. A programação usa o tempo global do vídeo e não reinicia a cada
capítulo; capítulos concluídos preservam seu tempo ao retomar. A opção só
reenquadra no ajuste **Preencher**; **Conter** preserva o quadro inteiro. Desmarcar
a opção mantém o enquadramento anterior. Pode acrescentar custo de processamento
na renderização e não garante melhoria de retenção. Teste uma nova geração para
comparar a abertura; checkpoints antigos não são compatíveis com a nova política.

API: `mixed_variable_pacing: true` (padrão). CLI: `--mixed-variable-pacing` ou
`--no-mixed-variable-pacing`. O campo `mixed_timeline_offset` é usado internamente
para posicionar cada capítulo no tempo total; deixe zero para um vídeo único.

## Controle de custo e retomada

O limite de imagens conta solicitações **iniciadas**, incluindo uma solicitação
que possa ter sido cobrada e falhado antes de disponibilizar o resultado. Nos
vídeos por capítulos, o orçamento é compartilhado entre os capítulos, não
reiniciado em cada parte. O fallback para imagem conta no mesmo limite de solicitações. Falhas da API de
análise visual não causam esse fallback.

Se o plano precisar de mais imagens do que o limite permite, o trabalho para
antes de novas encomendas de imagens e informa quantas são necessárias, o
limite e quantas solicitações já começaram. O planejamento pelo modelo de texto
pode ter custo mesmo quando esse bloqueio ocorre. Tente cenas de 15–20 segundos
para reduzir a quantidade de cenas ou revise o roteiro. Aumente o limite somente
se aceitar possíveis cobranças adicionais. A duração é desejada: mudanças de
contexto podem exigir cortes extras. Limite zero permite somente cenas de banco; um trecho que precise de
reconstituição interromperá a geração em vez de receber uma substituição inadequada.

O plano e os arquivos concluídos ficam em `storage/tasks/<id>/mixed-scenes.json`
e `storage/tasks/<id>/mixed/`. Resultados reutilizáveis são verificados por hash.
Uma imagem gerada e salva pode ser reutilizada após falha de renderização.
Uma solicitação com resultado desconhecido não é refeita automaticamente. Nesse
caso, confira o resultado e a cobrança no provedor antes de iniciar outra tarefa.
A retomada com o mesmo ID exige os mesmos textos, tempos e configurações visuais.

A correspondência de imagens e a precisão histórica precisam de revisão no
vídeo final; o modo misto não garante acerto visual de todas as cenas.

## API e CLI

A API existente `POST /api/v1/videos` aceita:

```json
{
  "video_subject": "História do café no Brasil",
  "video_script": "Seu roteiro completo…",
  "video_source": "mixed",
  "video_count": 1,
  "mixed_max_images": 12,
  "mixed_scene_duration": 10,
  "mixed_visual_validation": true,
  "mixed_vision_model": "gpt-4.1-mini",
  "mixed_max_candidates": 3,
  "voice_name": "pt-BR-AntonioNeural-Male",
  "subtitle_enabled": true
}
```

No CLI, use `--video-source mixed`, `--mixed-max-images 12` e
`--mixed-scene-duration 10`. A análise visual usa `--mixed-vision-model
gpt-4.1-mini` e `--mixed-max-candidates 3`; para desativá-la, use
`--no-mixed-visual-validation`. O modelo de texto e as APIs de material precisam
estar configurados normalmente. Para vídeos longos, combine com `--long-form`.

## Validação

Os testes cobrem Pexels/Pixabay/Coverr na mesma sequência, cenas históricas, limites,
reserva de orçamento, reutilização de imagens, falhas com resultado desconhecido,
interface e orçamento compartilhado entre capítulos. Um teste integrado usa
clipes e áudio reais gerados por FFmpeg e verifica cor, ordem e duração do vídeo
final. Chamadas aos modelos e bancos são simuladas; o teste com suas contas e
seu roteiro no Windows continua necessário.
