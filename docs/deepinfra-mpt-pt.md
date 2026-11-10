# DeepInfra — FLUX.1 Schnell no MPT

A integração existente de cenas foi estendida, mantendo SDXL Turbo disponível.
FLUX.1 Schnell é o padrão das novas gerações DeepInfra. Os demais provedores,
roteiro, áudio, legendas e pesquisa histórica mantêm seus serviços existentes.
Não há chamadas à API ao abrir a interface.

## Selecionar, configurar e testar

1. Abra **Configurar fontes de material → Imagens IA → DeepInfra — FLUX.1 Schnell**.
2. Configure a chave localmente ou forneça DEEPINFRA_API_KEY ao processo MPT.
3. Selecione **DeepInfra — FLUX.1 Schnell** no seletor **Modelo de imagens DeepInfra**.
4. Clique **Testar DeepInfra** para uma única imagem, com visualização e download.
5. Para cenas, escolha a fonte exclusiva **DeepInfra — FLUX.1 Schnell**, ou marque
   DeepInfra no modo misto. O modelo efetivo é o configurado no painel acima.

No modo misto, a prioridade atual dos bancos e os limites de imagens são mantidos.
Marcar DeepInfra só muda o gerador das novas imagens; não há troca automática para
outros geradores após erro. Se DeepInfra não estiver selecionada, seu conector não
é acionado pela produção. O SDXL Turbo anterior continua no seletor de modelos.

As variáveis DEEPINFRA_API_KEY e DEEPINFRA_IMAGE_MODEL prevalecem nas novas
solicitações. O modelo e os passos são congelados no job ao enviá-lo; uma alteração
posterior não muda uma geração já solicitada. Exemplo PowerShell, sem imprimir a chave:

```powershell
$env:DEEPINFRA_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'Chave DeepInfra' -AsSecureString)).Password
$env:DEEPINFRA_IMAGE_MODEL = 'black-forest-labs/FLUX-1-schnell'
.\webui.bat
```

O processo iniciado herda essas variáveis. A chave não é enviada a geradores de
texto nem gravada em prompts, manifestos, relatórios ou logs do conector.

## Thumbnails

Não existia gerador de thumbnails próprio nesta versão. O painel DeepInfra agora
oferece **Ativar geração de thumbnails DeepInfra**, desligado por padrão. Quando
ativado, preencha o prompt e clique **Gerar 1 thumbnail DeepInfra**. O resultado é
PNG 1280×720, mostrado na interface e disponível para download. A thumbnail é uma
imagem independente: não inicia roteiro, áudio, vídeo ou publicação no YouTube.

## Contrato FLUX

- Modelo: black-forest-labs/FLUX-1-schnell.
- POST https://api.deepinfra.com/v1/openai/images/generations.
- Authorization: Bearer, com a chave local.
- JSON: model, prompt, n=1, size e response_format=b64_json.
- Tamanhos solicitados: 1024x576 (16:9), 576x1024 (9:16), 512x512 (1:1).
- Resposta: data[0].b64_json, incluindo Base64 puro ou data URI de imagem;
  data[0].url também é aceito via downloader público HTTPS sem credenciais.
- O download por URL reutiliza a validação existente de HTTPS público, limites de
  bytes e redirects; o Bearer da API nunca é repassado ao servidor da imagem.
- PNG decodificado/validado, limite de pixels e bytes e remoção de metadados.
- FLUX é enquadrado à dimensão solicitada com recorte central proporcional,
  sem esticar. O vídeo continua usando o ajuste de quadro e resolução final do
  MPT; thumbnails têm recorte proporcional para 1280×720.

O contrato usa o endpoint e modelo solicitados. A disponibilidade e os parâmetros
no serviço real ainda precisam da validação com credenciais; o ambiente desta
entrega não possui uma chave DeepInfra configurada. Não há promessa de velocidade,
preço ou licença comercial. Confira essas informações no provedor.

## Contrato legado SDXL

Preservado POST https://api.deepinfra.com/v1/inference/stabilityai/sdxl-turbo,
com prompt, num_images=1, width, height, num_inference_steps (1–4) e guidance_scale=0.
O campo images em Base64 e a sinalização nsfw_content_detected continuam aceitos.
A seleção de passos não é enviada ao endpoint FLUX.

## Erros, limites e retomada

- 401/403: erro de autenticação/acesso, sem registrar chave ou corpo de resposta.
- 429: cooldown compartilhado por credencial, respeitando Retry-After numérico ou
  data HTTP. Sem prazo, usa 60 segundos locais; não é uma quota oficial.
- Uma chamada de geração por vez por credencial nesta instalação. Isso não mede
  solicitações feitas por outras aplicações ou computadores.
- Timeout de conexão 15 s; leitura configurável 30–1800 s. Sem HTTP retry automático
  ou redirects no POST autenticado. Não repete geração após resultado incerto.
- Limite de resposta 36 MiB e 20 megapixels antes de decodificar a imagem completa.
- deepinfra-image.json é gravado antes do envio; resposta salva antes da conversão.
  A retomada reutiliza imagem validada ou resposta persistida. Erros não acionam
  outro provedor nem fazem reformulação automática de prompts.
- Checkpoints SDXL antigos sem campo model permanecem recuperáveis como SDXL,
  mesmo com o novo padrão FLUX. Novos jobs registram modelo e fingerprint.
- O botão de preparar novo teste apenas libera uma próxima ação explícita; não
  envia uma imagem. Ele não cancela pedidos já enviados no servidor.

## Arquitetura e arquivos modificados

Mapa encontrado: VideoParams → validação das fontes → mixed_materials →
deepinfra_image.generate → PNG → renderizador de imagens e montagem existentes.
A interface configura a fonte em Main.py e os testes em deepinfra_settings.py.
O novo caminho de thumbnail reutiliza o mesmo conector e checkpoint.

Código:
- app/services/deepinfra_image.py: dois contratos, Base64/URL, normalização,
  thumbnails, timeouts, HTTP e cooldown compartilhado, checkpoints compatíveis.
- app/models/schema.py: deepinfra_model opcional, congelável no projeto.
- app/services/mixed_materials.py: modelo na assinatura e nos jobs por cena.
- app/services/long_form.py: apenas compatibilidade de fingerprints e campos de
  imagem na retomada por capítulos; as funções de roteiro e áudio não mudaram.
- webui/deepinfra_settings.py: seleção, Testar DeepInfra, recuperação e thumbnails.
- webui/Main.py: rótulos da fonte e orientação do modo misto.
- config.example.toml: modelo e toggle de thumbnail; configuração real preservada.

Testes: test/services/test_deepinfra_flux.py (novo), test_deepinfra_image.py,
test_mixed_materials.py e test_channel_skills.py (compatibilidade do novo campo).
Documentação e pacotes Windows também foram atualizados.

## Validação e teste real

437 testes passaram e 5 foram ignorados. Incluem Base64 válido/inválido, PNG,
URL sem credenciais, 401/403/429/503, ausência de reenvio, retomada SDXL, fonte
selecionável, clique explícito, thumbnail sem distorção e renderização real FFmpeg
com a resposta do provedor simulada. Os demais provedores permaneceram na regressão.

O teste real foi selecionado, mas ignorado por ausência de credenciais DeepInfra;
nenhuma imagem real foi solicitada nesta entrega. Para executá-lo na instalação
configurada, em ambiente de desenvolvimento com pytest disponível:

```powershell
$env:MPT_DEEPINFRA_LIVE_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest -q -rs test/services/test_deepinfra_flux.py::test_live_deepinfra_flux_when_credentials_configured
```

Esse teste faz uma única geração FLUX e pode consumir saldo. Sem chave, retorna
skipped, não passed. O botão Testar DeepInfra permite a mesma verificação na UI.

## Instalação e rollback

Feche o MPT, faça backup e extraia o ZIP na raiz da instalação; reabra webui.bat.
O pacote não inclui config.toml real, storage ou .venv e não instala dependências.
Para rollback, feche e restaure os arquivos de código do backup, preservando storage.
Os PNGs e os checkpoints permanecem nas pastas dos projetos/testes/thumbnails.
