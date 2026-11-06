# Google Flow automático como último recurso

Esta versão substitui o modo assistido. Só o login inicial exige intervenção.
A execução por navegador é uma integração não oficial por controles visíveis.
Seletores ainda precisam ser verificados na sessão real do usuário: testes
simulados não comprovam compatibilidade com o Flow atual. Mudanças no site podem
interromper o processo. Não há chamada a endpoints internos nem bypass de
CAPTCHA, login, segurança ou cotas.

## Instalar e conectar

Aplique o ZIP na instalação modificada, após fechar o MPT e fazer backup.
Tenha Chrome instalado e execute PREPARAR_FLOW_WINDOWS.bat uma vez. Reabra
webui.bat, selecione Misto e escolha **Bancos → ChatGPT → Flow automático**.
Informe nome do perfil e URL do projeto; use Cadastrar / conectar conta para
fazer login diretamente no Google e confira o avatar. Feche as janelas desse
perfil antes de gerar. Sessão local em storage/flow_browser/profiles; não
compartilhe a pasta nem informe sua senha no MPT. Não há rotação de contas.
Google pode impedir login num navegador controlado; a integração não contorna isso.

## Ordem de seleção

1. Tenta materiais dos bancos disponíveis, distribuindo os candidatos.
2. Sem clipe aprovado, solicita uma imagem à API do ChatGPT/OpenAI configurada.
3. A imagem recebida é guardada e comparada visualmente com a passagem.
4. Se o resultado for inutilizável ou rejeitado por falta de correspondência,
   tenta o Flow. Não muda de provedor em recusa de segurança ou erro técnico.

Esse encadeamento requer validação visual ativada e API de geração configurada.
A opção Flow direto continua separada e não passa pela geração OpenAI.

## Ações no navegador

O conector tenta confirmar Imagem, 16:9, x1 e Nano Banana 2.1, preencher o prompt,
enviar UMA vez, esperar uma imagem nova e baixar pelo botão do próprio resultado.
A imagem é validada e inserida na cena. Não baixa um arquivo antigo só porque
há um botão Download na página. Resultado múltiplo/ambíguo interrompe a execução.

A opção **Só enviar se mostrar custo de 0 créditos** vem ativada. Se esse custo
não estiver visível, o sistema para antes de enviar. Desativá-la permite usar
os créditos da conta. Não há garantia de gratuidade ou disponibilidade do modelo.
Controles sem seleção verificável também impedem o envio. CAPTCHA, limite,
logout, falha ou timeout interrompem sem repetir automaticamente.

## Preservação das correções anteriores

- Recusa explícita da API ou do Flow resulta no card editorial identificado.
- Uma recusa NÃO é reenviada a outro provedor nem reformulada.
- Erro de chave/modelo/serviço não provoca troca automática de provedor.
- Cada pedido preparado conta no limite: OpenAI e Flow podem consumir DUAS
  unidades para uma cena. Se não houver orçamento, o Flow não é aberto.
- Resultados OpenAI rejeitados ficam salvos para revisão, sem nova cobrança
  automática para refazê-los. Downloads Flow concluídos entram no checkpoint.
- Resultado desconhecido não é reenviado ao retomar.
- A fila continua sequencial; não repete clipes indevidamente.

Recomenda-se uma nova tarefa curta para o primeiro teste do DOM na conta real.
Não foi possível acessar ou validar o projeto privado do usuário neste ambiente.
