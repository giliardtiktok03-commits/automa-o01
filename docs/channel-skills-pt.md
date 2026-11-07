# 00 · Configurações de Skills

O novo bloco fica na primeira coluna, imediatamente acima das configurações do
roteiro. Ele permite instalar e selecionar instruções editoriais de arquivos
`SKILL.md`, mantendo múltiplas skills e uma cópia das versões usadas por projeto.

**Esta atualização fornece o suporte. Não instala nem ativa um perfil definitivo
de história militar, espionagem ou outro nicho.** As decisões editoriais do canal
devem ser definidas e aprovadas antes de preencher a primeira skill.

## Identidade do canal e decisões de cada vídeo

A skill pode registrar público, propósito, idioma preferido, estrutura narrativa,
fontes aceitáveis, tratamento de incertezas, estilo visual, direção musical e
perfil vocal desejado. O tema, o recorte e o ângulo de um vídeo continuam podendo
ser definidos nos campos de tema e instruções adicionais daquele projeto.

Para o canal em discussão, o nicho e a referência ArchiveInMinutes são contexto
prévio, não uma análise concluída nem uma receita validada. Não foram preenchidos
automaticamente público, idioma, duração, abertura, profundidade ou ângulos.

## Usar na interface

1. Expanda **Instalar ou gerenciar SKILL.md**.
2. Baixe o modelo vazio e preencha as regras aprovadas, ou carregue seu próprio
   arquivo UTF-8. O tamanho máximo é 24.000 bytes por arquivo.
3. Informe um identificador como `meu-canal`. Clique **Instalar skill**.
4. Marque **Ativar Skills editoriais** e selecione as skills desejadas.
5. A primeira selecionada é a principal. As demais complementam suas regras.
   Para mudar a ordem, remova e selecione novamente na ordem desejada.
6. Use a prévia do prompt do roteiro para revisar as instruções combinadas.

As configurações explícitas do projeto e o formato de resposta exigido pela
tarefa têm prioridade. Skills complementares não devem substituir a principal
em caso de conflito. Essa orientação é enviada ao modelo; a revisão editorial
do resultado continua necessária. Sem skills ativas, o prompt original é mantido.

## Formato

O corpo é Markdown. Um cabeçalho YAML opcional pode informar `name` e `version`.
Sem cabeçalho, o identificador é usado como nome. Exemplo genérico, para editar:

```markdown
---
name: Meu perfil editorial
version: "1.0"
---
# Público e propósito
Preencha as decisões aprovadas do seu canal.

# Roteiro
Defina o idioma, a estrutura, a abertura e a profundidade desejados.

# Temas e ângulos
Explique como escolher um recorte original e tratar fontes e incertezas.

# Visual e música
Defina orientações editoriais que ajudem o planejamento de cenas.
```

Há dois campos YAML opcionais adicionais:

- `voice_profile`: descrição de até 600 caracteres. É exibida como sugestão; não
  muda `voice_name`, o provedor, a voz aprovada ou a velocidade da narração.
- `music_prompt`: descrição musical de até 1.200 caracteres. Preenche o briefing
  de música gerada apenas quando não existe prompt musical explícito. Os
  provedores, custos e limites continuam os existentes. Não ativa um serviço de
  música sozinho nem cria endpoints AI33 de áudio.

O perfil vocal americano documental discutido anteriormente ainda precisa ser
consolidado dentro de uma skill aprovada. A busca e aprovação de vozes reais na
AI33 dependem de documentação verificável do catálogo de vozes, ainda pendente.

## Onde as instruções são aplicadas

O contexto acompanha o modelo central nas chamadas de análise de referência,
roteiro, palavras-chave, metadados de publicação e planejamento visual. Os prompts
de imagem produzidos pelo planejador recebem essa direção editorial. Novas
imagens sintéticas continuam sendo geradas exclusivamente pela AI33.Pro.

Isso não adiciona pesquisa automática na web, acesso ao NexLev, curadoria
histórica em arquivos externos ou verificação factual independente. Também não
sobrescreve roteiro ou áudio já fornecidos. Skills são instruções, não executores:
código, comandos e links dentro delas não são executados nem abertos pelo loader.
As regras de orçamento, provedores, fontes e voz são mantidas pelo código.

## Versões, fila e retomada

Instalações ficam em `storage/channel-skills/<identificador>/SKILL.md`. Editar
uma skill salva sua versão anterior em `revisions/<hash>.md`. Arquivar move a
pasta para `storage/channel-skills/_trash`, sem apagar projetos existentes.
O gerenciamento não contém uma função de execução de scripts.

São permitidas até oito skills ativas e 48.000 bytes de conteúdo combinado.
Cada projeto guarda identificador, nome, versão informada, texto e SHA-256.
O hash verifica o conteúdo salvo; não é uma assinatura de autoria ou confiança.
Não inclua chaves de API, senhas ou outros segredos em SKILL.md.

Na entrada da fila, a cópia é congelada. Editar, arquivar ou substituir a skill
na biblioteca não muda trabalhos já enviados. A retomada usa as instruções do
projeto salvo. Mudanças de skill não são aceitas silenciosamente em um mesmo
checkpoint de cenas. Para uma nova produção, a seleção usa versões instaladas.
Projetos antigos sem skills continuam com o comportamento padrão.

## Instalação e rollback

Feche o MPT, faça backup e extraia `MPT-Skills-Windows.zip` na pasta do programa.
Preserve `config.toml`, `storage` e `.venv`; nenhuma dependência nova é necessária.
Esta atualização inclui a integração AI33 anterior.

Para desativar a influência editorial, desmarque **Ativar Skills editoriais**.
Para reverter código, restaure o backup apropriado, preservando os arquivos de
skills, as cópias salvas nos projetos e os materiais pagos. Não remova snapshots
manualmente de projetos que serão retomados.
