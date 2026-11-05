# Pesquisa de referência por transcrição

Em **Configurações de roteiro → Pesquisa de referência (leve)**, cole uma
transcrição ou importe um arquivo TXT/SRT em UTF-8. Você pode informar o título
original. O campo **Tema do vídeo** orienta as sugestões para o seu novo conteúdo.

Selecione o provedor da análise e clique em **Analisar referência**:

- **Ollama (local)** é a opção inicial. Configure o endereço do seu servidor Ollama
  e o nome de um modelo de texto instalado em **Configurar modelo de IA**.
  Um modelo local pequeno, por exemplo de 3 bilhões de parâmetros, é um ponto
  de partida para reduzir o uso de recursos. O código não instala nem baixa
  modelos automaticamente. O custo de processamento fica na máquina que executa
  o modelo, sem depender de uma API paga.
- **API do ChatGPT (OpenAI)** utiliza a chave, o modelo e o endereço da OpenAI
  configurados no MPT. A transcrição é enviada a esse serviço ao clicar em analisar.
  O consumo da API é cobrado separadamente da assinatura do ChatGPT. Insira sua
  chave na configuração do aplicativo, nunca no texto da transcrição.

A escolha do provedor da análise é independente do provedor usado para gerar
vídeos. Uma falha do Ollama não aciona a OpenAI automaticamente. A troca de opção,
sozinha, também não envia uma solicitação.

## Resultado

A análise inclui resumo, avaliação do título fornecido, formato narrativo,
gancho inicial, público provável, etapas da narrativa e ritmo textual, além de
pontos fortes e oportunidades de melhoria. Trechos da transcrição fundamentam
o gancho e cada etapa. As citações são verificadas antes de exibir o resultado.

O modelo também sugere novos títulos, uma estrutura original e instruções para
escrever seu roteiro. Use **Adicionar às instruções do roteiro** para combinar
essas orientações com suas instruções atuais. O botão mantém o texto existente,
evita adicionar a mesma orientação duas vezes e avisa quando o limite de 2.000
caracteres seria ultrapassado. O roteiro e o vídeo não são gerados por esse botão.

Você pode baixar a análise como Markdown. O relatório permanece na sessão da
interface. Se alterar a referência, o tema, a língua da interface ou o provedor,
analise novamente antes de aplicar as orientações.

## Limites desta etapa

- Texto de 80 a 30.000 caracteres; arquivos de até 512 KB.
- O SRT fornece as falas; índices e tempos das legendas são removidos.
- A análise considera o texto: não mede retenção, velocidade real da fala,
  cortes, imagens, efeitos sonoros ou desempenho do vídeo.
- Para vídeos e gravações, obtenha primeiro a transcrição. Esta etapa não baixa
  vídeos nem carrega modelos de visão ou reconhecimento de voz.
- A qualidade depende do modelo escolhido. Se a resposta estiver incompleta ou
  contiver citações ausentes da fonte, o MPT pede nova análise em vez de apresentá-la
  como resultado válido. A interpretação editorial continua sujeita à revisão.

## Validação

```bash
uv run python -m pytest -q \
  test/services/test_reference_research.py \
  test/services/test_webui_reference_research.py
```

Os testes exercitam TXT/SRT, limites, respostas incompletas, citações inventadas,
seleção dos dois provedores e aplicação das orientações na interface. Chamadas
a modelos são simuladas; a validação real depende do Ollama ou da API configurada.
