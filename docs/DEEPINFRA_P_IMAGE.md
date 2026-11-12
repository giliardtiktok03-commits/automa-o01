# PrunaAI P-Image no DeepInfra existente

O catálogo ganhou **PrunaAI P-Image**, com ID exato **`PrunaAI/p-image`**.
A chave, o Bearer, os checkpoints, a política sem reenvio automático e o leitor de
imagens da integração DeepInfra atual são reutilizados. O padrão continua FLUX.1
Schnell; FLUX e SDXL Turbo permanecem disponíveis.

Somente adicionar o catálogo não seria suficiente: `VideoParams.deepinfra_model`
aceitava somente dois IDs e o serviço encaminhava apenas FLUX ao endpoint OpenAI.
A alteração estende essas condições existentes ao novo modelo. Não cria serviço,
não refatora o conector e não altera montagem, zoom, roteiro, narração ou bancos.

## Contrato

POST `https://api.deepinfra.com/v1/openai/images/generations`

Autenticação: `Authorization: Bearer <chave DeepInfra já configurada>`.

Exemplo 16:9, uma imagem:

```json
{
  "model": "PrunaAI/p-image",
  "prompt": "A documentary steam locomotive, wide composition, no text.",
  "n": 1,
  "size": "1024x576",
  "response_format": "b64_json"
}
```

O modelo passa pelo mesmo tratamento OpenAI-compatible que o FLUX: lê
`data[0].b64_json`, aceita base64 simples ou data URI de imagem, valida a
codificação e decodifica com Pillow. A imagem é convertida para RGB/PNG e usa o
ajuste de proporção já existente. Em 16:9, a saída é `image.png`, 1024×576.
O caminho retornado é o mesmo consumido pelo fluxo atual de materiais/MoviePy.
Uma resposta contendo JPEG base64 também é salva como PNG válido.

O serviço mantém uma imagem por solicitação. 9:16 e 1:1 também usam os tamanhos
existentes; nenhum formato novo de vídeo foi introduzido.

## Instalação e teste real no Windows

1. Feche o servidor do MPT e faça backup dos três arquivos indicados abaixo.
2. Mescle o ZIP na raiz do programa. Ele é **incremental**: contém somente os
   três arquivos de execução desta alteração e documentação. Não substitui
   `Main.py`, fontes de bancos, montagem, zoom ou configurações.
3. Reabra o MPT. Em configurações de fontes de material, abra **DeepInfra**.
4. Em **Modelo de imagens DeepInfra**, selecione **PrunaAI P-Image**.
   Reutilize a chave atual. Caso `DEEPINFRA_IMAGE_MODEL` esteja fixado no ambiente,
   ele continua tendo prioridade; confira o modelo efetivo informado na interface.
5. Informe o prompt do teste e clique uma vez em **Testar DeepInfra**. Esse botão
   existente solicita uma única imagem 16:9 e pode consumir saldo DeepInfra.
6. Confira a prévia e os detalhes: `model` deve ser `PrunaAI/p-image`, `width=1024`,
   `height=576`. Use **Baixar imagem de teste** para salvar o PNG.

O teste guarda seu registro em
`storage/deepinfra-tests/<id>/deepinfra-image.json`, com modelo, status, dimensões,
identificador da solicitação e hash quando salvo. Em erro HTTP, registra
`http_status`; o aviso mostra o status e informa ausência de reenvio automático.
Chave e Bearer não são incluídos nesses registros.

Se houver erro, não clique repetidamente em novo teste: use **Recuperar resultado
salvo do mesmo teste** quando aplicável. O registro existente impede reenvio
silencioso de uma solicitação cujo resultado não foi confirmado.

## Validação realizada

- 33 testes locais aprovados da integração DeepInfra existente e do novo modelo.
- Um teste antigo de API real do FLUX ficou desativado por opt-in.
- Requisição simulada confirma endpoint exato, ID com maiúsculas/minúsculas
  corretas, Bearer reutilizado, `n=1`, `size=1024x576` e base64.
- Respostas base64 sintéticas PNG/JPEG produzem PNG RGB válido em 16:9;
  abertura e leitura de frame no `ImageClip` do MoviePy aprovadas.
- HTTP 401/403/429/422/503 e base64/arquivo inválidos geram erros legíveis e
  preservam o registro sem realizar segunda solicitação automática.
- Retomada preserva o modelo de um trabalho salvo mesmo com outro modelo
  selecionado posteriormente. Testes existentes de FLUX e SDXL continuam passando.
- Catálogo e botão de teste conferidos na interface; renderizar/selecionar modelo
  não gera imagens automaticamente.

**Nenhuma imagem foi gerada na API DeepInfra neste ambiente.** A credencial não
estava disponível e o usuário escolheu executar o teste real no MPT do Windows.
Os resultados acima validam contrato/processamento local, não saldo, acesso ao
modelo, latência ou qualidade de imagem da conta real.

A documentação pública do modelo foi consultada em
https://deepinfra.com/PrunaAI/p-image/api. Ela confirma o ID, o endpoint OpenAI,
`size`, `n` e retorno base64. O tamanho 1024×576 também atende aos limites de
dimensões publicados (múltiplos de 16, entre 256 e 1440 pixels).

## Arquivos alterados

- `app/models/schema.py`: admite o novo ID no parâmetro existente.
- `app/services/deepinfra_image.py`: catálogo e extensão do caminho OpenAI já
  existente ao P-Image, inclusive decodificação/normalização.
- `webui/deepinfra_settings.py`: títulos/descrição do painel compatíveis com a
  seleção de mais de um modelo. O seletor reutiliza o catálogo atual.
- `test/services/test_deepinfra_p_image.py`: contrato, PNG/JPEG, MoviePy, seleção,
  erros e retomada. Testes não são necessários no ZIP de execução do Windows.
