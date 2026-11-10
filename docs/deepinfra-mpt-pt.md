# DeepInfra · SDXL Turbo

Provedor opcional de geração sintética: `stabilityai/sdxl-turbo`.
O ChatGPT continua nas funções de roteiro, prompts e validação visual.
Não usa OpenAI Image API, navegador Flow nem troca de gerador em falhas.

## Configurar e testar

1. Abra **Configurar fontes de material → Imagens IA → DeepInfra · SDXL Turbo**.
2. Cadastre a chave localmente. Também aceita `DEEPINFRA_API_KEY` no ambiente do processo MPT.
3. Mantenha inicialmente **1 passo** (configurável de 1 a 4).
4. Clique **Gerar 1 imagem de teste DeepInfra (cobrado)** uma vez.
5. Confira a qualidade e o consumo no painel DeepInfra antes de produzir um vídeo longo.

Para modo misto, mantenha Pexels, Pixabay e Coverr marcados e marque DeepInfra.
Prioridade dos geradores marcados: DeepInfra, Flow, Grok, AI33. Não há troca automática após erro.
A DeepInfra fica DESMARCADA por padrão. O limite geral de imagens vale para ela,
mesmo se a opção de Grok ilimitado estiver salva. Também existe a fonte exclusiva
**DeepInfra · SDXL Turbo**, que usa imagens sintéticas em todas as cenas.

## Contrato e limitações

- `POST https://api.deepinfra.com/v1/inference/stabilityai/sdxl-turbo`
- `Authorization: Bearer <chave local>`
- Corpo: `prompt`, `num_images: 1`, `width`, `height`, `num_inference_steps`, `guidance_scale: 0`.
- Dimensões: 1024×576 (16:9), 576×1024 (9:16), 512×512 (1:1).
- Resposta: `images` (base64 ou data URI), `nsfw_content_detected`, `request_id`, `inference_status`.
- O conector verifica a imagem e salva PNG; não executa URLs de resposta como downloads.
- São ilustrações/reconstruções, não fotografias históricas autênticas. Turbo prioriza poucos passos;
  qualidade, fidelidade e tempo de geração precisam de avaliação real.

A documentação web indicada não pôde ser acessada pela rede do ambiente de desenvolvimento.
O contrato foi conferido no SDK oficial `deepinfra@2.0.2`, publicado no npm e vinculado
pelo pacote a https://github.com/deepinfra/deepinfra-node. Nenhuma dependência foi instalada.
Isso NÃO confirma preço atual, disponibilidade do modelo na conta, limites de uso ou
licença comercial. Confira essas condições no provedor antes de publicar imagens.

Fontes:
- https://docs.deepinfra.com/tutorials/stable-diffusion#quick-start
- https://www.npmjs.com/package/deepinfra
- https://deepinfra.com/stabilityai/sdxl-turbo

## Cobrança e retomada

Não há chamada paga ao abrir a interface. Testes exigem clique explícito.
Não há cotação financeira prévia nesta integração: o controle é de quantidade de imagens,
não de valor. Um preço eventualmente retornado é apenas informativo, não um teto de custo.

O registro `deepinfra-image.json` é salvo antes do envio. A resposta é persistida antes da
conversão. Retomadas reutilizam imagem válida ou resposta salva e não repetem pedidos
cujo resultado ficou incerto. Falhas HTTP/timeout param o projeto; nenhum outro gerador
é acionado. Recusa sinalizada por `nsfw_content_detected` usa o card editorial já existente,
sem reformular o pedido. As credenciais não entram no registro da imagem.

Os testes automatizados usam respostas simuladas e não validam latência ou geração real.

## Atualização e rollback

Feche MPT e faça backup dos arquivos substituídos antes de extrair o ZIP na raiz.
Não substitua `config.toml`, `.venv` nem `storage` — esses itens não estão no pacote.
Para rollback, desmarque DeepInfra para novas execuções e restaure os arquivos do backup.
Preserve os projetos e registros pagos. Não retome um projeto com provedor novo usando
código antigo; mantenha o backup completo da instalação para reconciliar esses projetos.
