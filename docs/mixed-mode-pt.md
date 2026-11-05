# Modo misto: Pexels + Pixabay + imagens IA

O modo misto planeja cenas a partir das passagens da narração. Ele mantém a
sequência e pode combinar vídeos dos dois bancos com imagens geradas no mesmo
vídeo final. A alternância depende do contexto, não de uma regra mecânica de
uma fonte a cada cena.

## Configuração no Windows

1. Em **Configurar fontes de material**, preencha sua chave do Pexels e sua chave
   do Pixabay, selecionando cada serviço na seção de bancos de vídeo. Basta um
   banco configurado para executar; com os dois, o modo distribui as buscas e
   tenta a outra fonte quando a primeira não entrega material utilizável.
2. Na seção de imagens, configure **Texto-para-imagem compatível com OpenAI**:
   endereço real da API, modelo disponível na sua conta e chave quando exigida.
   Os textos cinza de exemplo não contam como valores preenchidos.
3. Volte a **Configurações do Vídeo → Fonte do Vídeo** e selecione
   **Misto: Pexels + Pixabay + imagens IA**.
4. Escolha o **máximo de imagens IA no vídeo completo** (padrão: 12) e a duração
   desejada de cada cena (padrão: 10 segundos).
5. Mantenha um vídeo por execução. Para este primeiro teste, use o roteiro curto
   já aprovado e mantenha as legendas ativadas para obter tempos mais precisos.

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

Passagens classificadas como históricas — e menções explícitas a escravidão,
abolição, séculos ou datas históricas — são direcionadas para ilustrações, em vez
de clipes modernos de banco. Os prompts pedem contexto de época e evitam prédios,
roupas, veículos e máquinas contemporâneos. As imagens são reconstituições
ilustrativas; não constituem documentos históricos autênticos.

Para passagens atuais, as buscas são específicas de cada cena. O modo prioriza
candidatos ainda não usados quando disponíveis. Se nenhum banco devolver um
arquivo utilizável, pode gerar uma ilustração, dentro do orçamento disponível.
Uma busca sem resultado também pode decorrer de falha da API: consulte os logs.
Não há inspeção visual automática dos clipes nesta versão. A qualidade ainda
depende dos resultados do banco, do planejamento e do modelo de imagem.

As cenas são renderizadas em sequência, com duração controlada em quadros. O
modo usa cortes simples e velocidade normal para preservar a linha do tempo;
os controles de transição, duração máxima de clipe e velocidade comuns ficam
inativos. A duração de cena do modo misto é a opção relevante. As palavras-chave
globais antigas não são usadas para planejar as cenas desse modo.

## Controle de custo e retomada

O limite de imagens conta solicitações **iniciadas**, incluindo uma solicitação
que possa ter sido cobrada e falhado antes de disponibilizar o resultado. Nos
vídeos por capítulos, o orçamento é compartilhado entre os capítulos, não
reiniciado em cada parte. Imagens previstas para passagens históricas têm verba
reservada antes de gastar o restante com buscas de banco sem resultado.

Se o plano precisar de mais imagens do que o limite permite, o trabalho para
antes das primeiras encomendas de imagens. Ajuste o limite ou o roteiro para
prosseguir. Limite zero permite somente cenas de banco; um trecho histórico que
exija imagem interromperá a geração em vez de receber uma substituição moderna.

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

Os testes cobrem Pexels/Pixabay na mesma sequência, cenas históricas, limites,
reserva de orçamento, reutilização de imagens, falhas com resultado desconhecido,
interface e orçamento compartilhado entre capítulos. Um teste integrado usa
clipes e áudio reais gerados por FFmpeg e verifica cor, ordem e duração do vídeo
final. Chamadas aos modelos e bancos são simuladas; o teste com suas contas e
seu roteiro no Windows continua necessário.
