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

Para impedir planos dominados por IA, cada plano admite no máximo um quarto das
cenas com imagens geradas, arredondado para baixo, permitindo uma cena em planos
curtos. O limite de solicitações configurado continua valendo e pode ser menor.
Em vídeos por capítulos, a proporção é validada em cada capítulo e o limite de
solicitações continua compartilhado. A proporção conta cenas, não segundos de vídeo.
Planos que excedam essa proporção param antes de encomendar imagens; o
planejamento de texto pode ter custo. Novas tarefas usam essa política; não
reutilize IDs de checkpoints anteriores à atualização.

As buscas tentam todos os bancos disponíveis e até duas consultas alternativas
aprovadas para a mesma cena. Sem um arquivo utilizável, o trabalho interrompe
com aviso: **uma busca vazia ou falha de API não encomenda uma imagem IA extra**.
Os logs mostram cena, provedor e consulta para diagnóstico, sem imprimir chaves.
Ao concluir cada plano, a interface e o log mostram quantas cenas vieram de
Pexels, Pixabay, Coverr e IA. Um banco sem resultados pode terminar com zero
cenas; estar cadastrado não garante que seu acervo tenha material utilizável.
Não há inspeção visual automática dos clipes: revise o vídeo final, pois os
resultados do banco e a avaliação do planejador ainda podem estar incorretos.

As cenas são renderizadas em sequência, com duração controlada em quadros. O
modo usa cortes simples e velocidade normal para preservar a linha do tempo;
os controles de transição, duração máxima de clipe e velocidade comuns ficam
inativos. A duração de cena do modo misto é a opção relevante. As palavras-chave
globais antigas não são usadas para planejar as cenas desse modo.

## Controle de custo e retomada

O limite de imagens conta solicitações **iniciadas**, incluindo uma solicitação
que possa ter sido cobrada e falhado antes de disponibilizar o resultado. Nos
vídeos por capítulos, o orçamento é compartilhado entre os capítulos, não
reiniciado em cada parte. Não há substituição paga automática quando as buscas de banco falham.

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
  "voice_name": "pt-BR-AntonioNeural-Male",
  "subtitle_enabled": true
}
```

No CLI, use `--video-source mixed`, `--mixed-max-images 12` e
`--mixed-scene-duration 10`. O modelo de texto e as APIs de material precisam
estar configurados normalmente. Para vídeos longos, combine com `--long-form`.

## Validação

Os testes cobrem Pexels/Pixabay/Coverr na mesma sequência, cenas históricas, limites,
reserva de orçamento, reutilização de imagens, falhas com resultado desconhecido,
interface e orçamento compartilhado entre capítulos. Um teste integrado usa
clipes e áudio reais gerados por FFmpeg e verifica cor, ordem e duração do vídeo
final. Chamadas aos modelos e bancos são simuladas; o teste com suas contas e
seu roteiro no Windows continua necessário.
