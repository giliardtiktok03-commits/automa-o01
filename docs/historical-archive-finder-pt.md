# Historical Archive Finder — MPT

## Comportamento entregue

Módulo global, independente de Skills, inicialmente **OFF**. Fica em
**Configurações do Vídeo → Historical Archive Finder · Desativado**.

A especificação original do pacote previa revisão manual. As instruções posteriores
substituem essa parte: **não existe aprovação manual, nem fila aguardando permissão**.
Direitos desconhecidos/restritos e itens explicitamente sinalizados como IA são ignorados.
Na produção, a ordem é:

1. Acervos históricos com direitos suficientemente claros e correspondência editorial.
2. Bancos/provedores visuais já habilitados para o projeto.
3. IA já habilitada, respeitando o limite de imagens e as regras existentes de retomada.

A IA recebe a narração e o prompt de cena, não a imagem descartada do acervo como
referência de cópia. O arquivo de origens identifica esse fallback como
`illustrative_reconstruction`, com `illustration: true`. Isso não cria selo visual
sobreposto à imagem: é a classificação no registro editorial e no plano da cena.
Recusas de segurança continuam usando o tratamento anterior; não se reformula um
pedido recusado para tentar contornar o provedor.

Se todas as fontes de fallback estiverem desabilitadas ou o orçamento de imagens
acabar, permanecem as falhas normais de falta de material/limite. Não se inventa
material nem se habilita um gerador pago por conta própria.

## Ativação

1. Abra o painel Historical Archive Finder na coluna de vídeo.
2. Ative a pesquisa. LOC, NARA e Commons são selecionados por padrão, mas o módulo
   inteiro inicia desativado e cada fonte pode ser desmarcada.
3. Use **Automático: acervos → bancos → IA habilitada**.
4. Mantenha seus bancos e DeepInfra/Grok/AI33/Flow conforme suas preferências atuais.
   O módulo não altera a seleção desses provedores.
5. Configure a chave NARA localmente, se desejar usá-la. Também aceita `NARA_API_KEY`.
   A falta dessa chave é informada e não bloqueia LOC/Commons.
6. Faça um vídeo curto e confira as origens e os créditos antes de produzir em escala.

O modo **Somente pesquisa** salva candidatos/metadados e mantém o fluxo visual
existente: não baixa nem insere arquivos históricos. A interface permite pesquisar
um projeto salvo em segundo plano, cancelar essa pesquisa, consultar prévias e
exportar os dados, sem exigir essas ações para produzir um vídeo automaticamente.

Desligar o toggle é verificado pelo backend, inclusive entre pedidos e durante a
leitura de um download. Não apaga arquivos, registros ou vídeos já existentes.
Não há rede, criação de buscas ou geração de consultas do módulo quando OFF.

## Fontes e contratos

- **LOC (conector substituído pelos três serviços públicos)**:
  1. JSON/YAML API: pesquisa e metadados, usando a representação JSON (`fo=json`).
  2. IIIF Image Services: consulta `info.json` e solicita imagem JPEG dimensionada,
     respeitando dimensões/capacidades anunciadas, sem ampliação ou recorte automático.
  3. Text Services: lê OCR divulgado pelos registros (texto, ALTO XML, hOCR ou JSON
     de palavras/coordenadas) e salva o texto por cena. Não inventa endpoints nem
     gera OCR inexistente; não instala Tesseract ou usa uma IA paga para isso.
  A opção continua única no painel. **Nenhuma chave ou autenticação LOC** é solicitada.
  O módulo `providers/loc_services.py` contém os três clientes; `loc.py` os coordena.
  Imagens/textos só são recuperados automaticamente com direitos claros. NARA/Commons
  e o fallback permanecem preservados.
- **NARA**: `GET https://catalog.archives.gov/api/v2/records/search?q=...`;
  cabeçalho `x-api-key`. Normaliza registros/digital objects e mantém as restrições
  originais. “Unrestricted” isoladamente não é tratado como domínio público.
- **Wikimedia Commons**: MediaWiki Action API `action=query`, `generator=search`,
  namespace 6, `prop=imageinfo|categories`, `iiprop=url|extmetadata|size|mime`.
  Licença, autoria, crédito, instituição e URL são específicas do arquivo.
- **Europeana/Internet Archive**: fase posterior, explicitamente desabilitados
  e sinalizados como pendentes. Não são apresentados como conectores funcionais.

As páginas web das três instituições foram bloqueadas pela rede do ambiente de
implementação (HTTP 403 do proxy). Foram consultados os repositórios oficiais
abaixo, incluindo o exemplo atual NARA v2 com autenticação e seu limite mensal
publicado. Não foi feito teste autenticado com uma chave NARA real.

Fontes:
- https://www.loc.gov/apis/
- https://github.com/LibraryOfCongress/data-exploration
- https://www.archives.gov/research/catalog/help/api
- https://github.com/usnationalarchives/Catalog-API
- https://commons.wikimedia.org/wiki/Commons:API
- https://github.com/wikimedia/mediawiki-api-demos

A integração está implementada e testada com fixtures. Compatibilidade com respostas
reais, condições atuais, acesso, disponibilidade e limites concedidos à conta ainda
precisam de validação na rede do usuário. Não se considera isso já validado.

## Consultas, seleção e direitos

As cenas vêm do planejamento/SRT já existente. Nos provedores tradicionais, o
adaptador usa segmentos da narração e seus tempos, sem mudar o fluxo quando OFF.
As consultas mantêm identificadores e datas apoiados pela narração ou pelo período
explicitamente informado pelo usuário. O termo em inglês já fornecido pelo
planejador é aproveitado; opcionalmente o modelo central pode elaborar consultas
em inglês, com custo próprio. Essa opção começa OFF. Sem ela, não existe promessa
de tradução automática para todos os idiomas.

Ranking explicável: evento 30%, tempo 25%, entidades 20%, qualidade 15%, direitos
10%. Datas/equipamentos conflitantes e ausência de correspondência temática impedem
seleção automática. O ranking não decide direitos e não prova autenticidade visual.

Política automática conservadora:

- CC0/Public Domain Mark explícitos: elegíveis.
- Declaração explícita e não condicional de domínio público: elegível.
- CC BY/CC BY-SA de versões reconhecidas: elegíveis somente com autoria e atribuição.
- NC, ND, “all rights reserved”, uso restrito: excluídos.
- Direitos ausentes, atribuição incompleta, “no known restrictions” e declarações
  condicionais/territoriais: ignorados, sem solicitação de aprovação.
- Itens do Commons podem ser modernos ou ilustrativos. Anotações explícitas de IA
  são filtradas, mas metadados não garantem que toda imagem represente um fato autêntico.

O estado interno de classificação `needs_review` continua distinguindo direitos
incertos no esquema de metadados, mas o estado operacional é `skipped_unknown_rights`:
o item não é baixado/usado e não existe interface ou pausa de aprovação.

## Arquivos, formatos e créditos

```
storage/tasks/<id>/historical_archive/
    manifest.json
    search_log.json
    sources_and_credits.md
    sources_and_credits.json
    scene_001/approved/<sha256>.png
    chapter_001_scene_001/approved/<sha256>.mp4
```

Candidatos e metadados originais ficam no manifesto. Não se baixam originais em
massa para triagem. Créditos listam **somente itens efetivamente usados em cenas
renderizadas**, nunca todos os resultados pesquisados. Podem ser aproveitados na
descrição; o módulo não publica nem altera automaticamente a descrição do YouTube.

São aceitas imagens decodificáveis pelo Pillow e filmagens MP4/WebM validadas por
FFmpeg. A extensão é determinada pelo conteúdo, arquivos temporários são removidos
e a gravação é atômica. HTML disfarçado de imagem, arquivos vazios e URLs fora dos
hosts oficiais permitidos são rejeitados. Paths são limitados à tarefa.

Documentos/mapas fornecidos como imagem entram normalmente. SVG, PDF e DjVu do
Commons podem usar a prévia raster indicada pela própria API; o manifesto informa
essa variante e conserva o URL original. Documentos multipágina usam a primeira
página da prévia, não uma montagem de todas as páginas.

PDF bruto exige PyMuPDF para validação/rasterização, se já instalado. Ele **não foi
adicionado como dependência obrigatória**. Sem ele e sem prévia raster, esse item é
ignorado, o erro fica registrado e o pipeline usa as fontes habilitadas. Não há
conector genérico de SVG/PDF ou OCR automático de todo documento.

Respeita a duração, a ordem e o movimento configurados; imagem estática continua
estática. “Preservar proporção original” aplica contain/padding às imagens de arquivo,
sem alterar a preferência global dos outros materiais. Deduplicação por ID/URL e
checksum evita inserir o mesmo arquivo repetidamente em cenas distintas.

## Limites, cache e cancelamento

Defaults locais conservadores, editáveis; não são alegações de limites oficiais:
5 candidatos/cena; 30 downloads únicos/vídeo; 50 MB/arquivo; 20 s/pedido; cache 24 h;
intervalo mínimo de 2 s para NARA/Commons; LOC com tetos separados de 20/min para
JSON/YAML, 150/min para IIIF Imagens e 150/min para Texto/OCR; até 1 retry de erro temporário com
backoff/jitter; teto local de 1000 pedidos NARA/mês.

O cache usa provider/URL/consulta/filtros, sem chaves no identificador. Há
serialização por provider dentro do processo. `Retry-After` é persistido e impede
insistência; 401/403/429 não causam troca de conta nem tentativa de contorno.
Os downloads/limites da mesma tarefa são compartilhados entre capítulos.
A pesquisa editorial em segundo plano tem uma única thread e pode ser cancelada.

Configurações globais usam o prefixo `historical_archive_` dentro de `[app]`, seguindo
a persistência e os snapshots já existentes do MPT. O arquivo `config.toml` do
usuário não é substituído pela atualização. A versão anterior permanece compatível
quando a opção está OFF, inclusive nos fingerprints de capítulos antigos.

## Testes e pendências

A suíte cobre OFF sem rede/criação de buscas, ativação em runtime, preservação das
preferências, cancelamento, fontes isoladas, credenciais ausentes, cache, Retry-After,
limite mensal NARA, deduplicação, direitos, rejeição de arquivos, paths, consultas,
relatórios usados-only, fallback para bancos/IA e renderização real horizontal,
vertical, filmagem e montagem de cenas com FFmpeg.

Pendências explícitas:
- Europeana e Internet Archive (conectores de fase seguinte).
- Teste opcional das três APIs reais; NARA exige a chave e acesso de rede.
- OCR, animação/seleção automática de páginas de documentos longos e suporte nativo
  a PDF/SVG sem prévias/conversor disponível.
- Verificação jurídica/autenticidade histórica absoluta: os metadados são indícios,
  não garantias. O modo automático exclui situações incertas em vez de pedir aprovação.

Nenhum teste chama um gerador pago, instala dependências ou usa chaves reais.

## Atualização, retomada e rollback

Feche MPT, faça backup e extraia o ZIP na raiz; abra `webui.bat`. Não remova `.venv`,
`storage` ou `config.toml`. Não há migração destrutiva nem instalação adicional.

Projetos mistos/imagens usam a retomada já existente. Para stock/local, quando há
contexto histórico salvo, o painel permite continuar com áudio/SRT preservados e
validados por checksum. Projetos concluídos não são sobrescritos. Capítulos usam a
retomada de capítulos existente.

Para desativar, basta desligar o toggle: novos pedidos param e os arquivos ficam.
Para rollback de código, mantenha o módulo OFF e restaure os arquivos do backup;
não apague material ou manifestos de projetos em andamento.


## Revisão LOC — três serviços públicos

Os tetos solicitados (20/150/150 por minuto) são impostos pelo backend e podem apenas
ser reduzidos na configuração. Janela móvel de 60 segundos, espaçamento e registros
persistidos coordenam threads/processos desta instalação; tentativas repetidas também
contam. Cache não consome novo pedido. Outras aplicações/instalações no mesmo IP não
são contadas por este armazenamento local.

429 e 403 da LOC gravam cooldown persistente, respeitando `Retry-After` em segundos
ou data HTTP. 503 com `Retry-After` também interrompe sem insistir. Uma espera longa
não é encurtada por outra resposta simultânea. Durante o bloqueio, não se alterna
entre JSON/Imagem/Texto para tentar contorná-lo. Sem prazo informado, usa-se o cooldown
local configurado (300 s por padrão), que não é uma promessa de prazo de liberação.
Outros erros temporários têm retry limitado e backoff/jitter, sempre dentro da quota.

OCR depende do conteúdo disponibilizado pelo registro. A primeira página/arquivo é
o padrão; até cinco podem ser configurados. Cada texto é limitado (60000 caracteres
por arquivo por padrão), com indicação de truncamento, formato e fonte. O arquivo
fica em `scene_XXX/candidates/<id>.ocr.txt`. Não altera a narração, o roteiro ou as
legendas e não comprova precisão histórica. URLs sem OCR e formatos não reconhecidos
são registrados como indisponíveis, sem bloquear as fontes restantes.

Referências oficiais consultadas pelo repositório `LibraryOfCongress/data-exploration`,
commit `087065cd1e89bad45c06095933850bb96c3e77b3`:
- `loc.gov IIIF API/IIIF.ipynb`: `info.json`, formatos, dimensões e processamento IIIF.
- `loc.gov JSON API/LOC.gov JSON API.ipynb`: API de metadados.
- `loc.gov JSON API/Chronicling_America/ChronAm-download_results.ipynb`: URLs de recursos
  e arquivos XML de OCR publicados pelo registro.

O acesso direto às páginas oficiais continua bloqueado pelo proxy do ambiente. Os
limites acima implementam a solicitação recebida; não foram revalidados por uma chamada
real ao site. Os testes usam fixtures, incluindo limites por minuto, 429/403/503,
Retry-After, cache, OCR, redimensionamento IIIF e ausência de autenticação. A validação
com registros reais que disponibilizem imagem IIIF e OCR continua pendente na rede local.
