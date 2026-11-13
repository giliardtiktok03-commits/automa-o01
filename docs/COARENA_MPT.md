# Coarena no MoneyPrinterTurbo

A Coarena foi adicionada como provedor independente de texto, usando o adaptador OpenAI-compatible já existente. Nenhum novo cliente HTTP, serviço de autenticação ou dependência foi criado. Anthropic Claude, OpenAI, ChatGPT/Codex e os demais provedores foram preservados.

## Configuração na interface

Em **Configurações → Provedores/LLM**, selecione **Coarena** e preencha:

| Campo | Valor |
|---|---|
| API Key | Sua chave Coarena, obtida no painel do serviço |
| Base URL | `https://coarena.ai/api/v1` |
| Model Name | `claude-fable-5` ou outro ID disponível para sua conta |

Salve e use o teste de conexão/geração já disponível no MPT. A chave deve ser informada somente na instalação local, nunca no chat ou repositório. O modelo padrão foi escolhido a partir do exemplo da documentação e confirmado no catálogo público; não foi selecionado com base em benchmark de qualidade. Você pode trocar pelo modelo que preferir.

Para quem configura manualmente o TOML, ajuste estes campos na seção `[app]` que já existe, sem apagar as outras opções ou duplicar a seção:

```toml
llm_provider = "coarena"
coarena_base_url = "https://coarena.ai/api/v1"
coarena_model_name = "claude-fable-5"
# Preencha sua chave somente no arquivo local ou pela interface:
coarena_api_key = ""
```

## Relação com os comandos Anthropic enviados

Os comandos `ANTHROPIC_BASE_URL=https://coarena.ai/api` e `ANTHROPIC_AUTH_TOKEN=$COARENA_API_KEY` são a forma documentada para um cliente **Anthropic**, que usa Messages. A documentação Coarena também oferece a mesma chave no formato **OpenAI-compatible**, com base `https://coarena.ai/api/v1`, autenticação `Authorization: Bearer` e `POST /api/v1/chat/completions`.

O MPT já tem esse segundo adaptador; por isso foi reaproveitado. **No campo Base URL do provedor Coarena no MPT, use `/api/v1`, não apenas `/api`.** Não é necessário executar `export` no Windows. Esses comandos de shell não são importados automaticamente pela nova configuração; preencha a chave no campo Coarena do MPT. O provedor Anthropic e o isolamento de credenciais do Claude Code continuam com o comportamento anterior.

## Usar na Historical Documentary Director

Para roteiro e pacote editorial, selecione **Coarena** como provedor do canal. Para fazer também a pesquisa sem chave OpenAI separada:

1. Abra **00 · Configurações de Skills → Historical Documentary Director → 00.1 → Configurar canal, Skills e autorização → Avançado · modelos e fontes da pesquisa**.
2. Escolha **Modo de pesquisa: Pesquisa pública + Coarena (API)**.
3. Escolha **Provedor do roteiro: Coarena** e o modelo desejado, ou deixe vazio para usar o modelo configurado do provedor.
4. Salve e envie um **novo lote**. Para o primeiro teste, escolha somente pacote editorial, um ângulo e mantenha a análise visual de thumbnails de referência desligada.

Esse modo usa a descoberta pública já implementada (índice da Wikipédia em inglês e referências externas), leitura HTTPS, citações conferidas e a API Coarena para consultas, seleção, dossiê, análise, ângulos, revisões, roteiro, descrição/tags e três briefings de thumbnail. O Blueprint, quando exigido, também usa Coarena. Não oferece busca web nativa da Coarena nem trata texto de modelo como fonte verificada.

O modo **ChatGPT/Codex por login** continua exclusivo dos conectores por login e não passa a chamar Coarena silenciosamente. O modo **API OpenAI** continua usando pesquisa OpenAI e pode usar Coarena separadamente para roteiro. Alterações no canal valem para novos lotes; configurações congeladas de tarefas anteriores são preservadas.

A análise visual de referências continua exigindo API OpenAI e é bloqueada antes da pesquisa nos modos públicos quando há thumbnails para analisar. A validação visual dos bancos também é uma integração separada com OpenAI. Para vídeo sem chave OpenAI, selecione somente imagens DeepInfra e desative essa validação; o DeepInfra mantém sua própria cota/cobrança. Narração, Pexels/Pixabay, zoom, montagem e publicação não foram modificados. Publicação automática permanece desligada.

## Limites e falhas

A [documentação Coarena](https://coarena.ai/docs) anuncia atualmente US$ 5/dia de uso custeado pelo serviço, 30 solicitações/minuto e duas simultâneas; a conta pode ter limite diário adicional. Isso é uma condição divulgada pelo serviço, não uma garantia do MPT. Consulte o painel para os limites reais e atuais. O MPT não solicita aumentos de limite, não registra contas e não envia feedback automaticamente.

Falhas de autenticação/permissão, cota ou servidor seguem o tratamento de erros existente; não viram roteiro bem-sucedido e não causam troca automática de provedor. Na Skill, chamadas remotas usam os checkpoints e a política de repetição já existentes, com revisão antes de repetir uma chamada de resultado desconhecido. A cota Coarena se aplica às etapas editoriais de cada ângulo; a fila segue processando um vídeo por vez.

## Verificação

- Documentação pública e `GET https://coarena.ai/api/v1/models` consultados sem chave. `claude-fable-5` e `claude-sonnet-5-5`, entre outros IDs, estavam no catálogo retornado. O catálogo e as permissões podem mudar.
- Testes com o SDK OpenAI real e transporte HTTP simulado confirmaram URL, Bearer token, modelo padrão/customizado, corpo e leitura da resposta; sem autenticação ou chamadas pagas reais.
- Testes cobriram 401/403/429/500, ausência de chave antes da rede, configuração congelada, ausência de troca para OpenAI e separação entre pesquisa por login e Coarena.
- Teste editorial completo, com rede/modelo simulados: pesquisa e ângulo original → pesquisa independente do pacote → roteiro de 405 palavras → descrição com referências → tags/hashtags → três briefings → exportação, tudo pelo provedor selecionado Coarena e sem chave de pesquisa OpenAI.
- Bateria: **434 testes passaram, 2 foram ignorados e 20 subtestes passaram**. Inclui catálogo, transporte, configuração de interface, pesquisa pública, Skill/fila, Blueprint, AUTOPILOT, narração/vídeo e P-Image. As condições de ignorar os dois testes são anteriores a esta alteração.

Não foi realizada geração autenticada real: não há chave Coarena neste ambiente. Esse teste precisa ser feito na instalação Windows após configurar a chave. A disponibilidade pública do catálogo não confirma saldo nem permissão de uma conta específica.

Arquivos principais: catálogo `app/models/llm_provider.py`, modos de canal em `app/models/autopilot.py`, `app/services/autopilot/{editorial,public_research}.py`, proteção visual do executor da Skill, seleção explícita de provedor para Blueprint, seletores dentro da Skill e textos de configuração. A integração HTTP em `app/services/llm.py` não precisou ser alterada.

No Chromium/Playwright, o modo **Pesquisa pública + Coarena (API)** e o provedor **Coarena** foram exibidos dentro do formulário da Skill e preservados após salvar; não houve exceção de interface ou chamada ao modelo nessa verificação.
