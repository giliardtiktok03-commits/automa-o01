# Google Flow pelo navegador — perfil local assistido

A integração atual preserva o gerador pela API e adiciona uma opção assistida no
modo misto. Não é integração oficial Google nem promessa de geração gratuita.
Não é automação sem supervisão: você confirma a geração e baixa cada imagem.

## Instalação e cadastro

1. Com o MPT fechado, aplique os arquivos da atualização sobre a instalação
   modificada existente, após backup.
2. Tenha Google Chrome instalado. Execute `PREPARAR_FLOW_WINDOWS.bat` uma vez.
   Ele instala a dependência opcional Playwright no Python do projeto. Não baixa
   um novo navegador nem altera as dependências básicas do MPT.
3. Abra `webui.bat`. Em Configurações do Vídeo, escolha o modo Misto.
4. Em Gerador de imagens do modo misto, escolha Google Flow — navegador assistido.
5. Nome do perfil: `principal`. Link do projeto: cole o seu endereço HTTPS
   `https://flow.google.com/project/<UUID>`.
6. Clique em Cadastrar / conectar conta no Google Flow. Faça login DIRETAMENTE
   no Google e confira o avatar/conta no Flow. Não informe senha no MPT ou chat.
7. Feche TODAS as janelas desse perfil antes de iniciar a geração no MPT.

O nome/link ficam nas preferências da interface. A sessão do Chrome fica apenas
em `storage/flow_browser/profiles/<nome>`. Essa pasta contém dados sensíveis de
sessão: não compartilhe nem inclua em atualizações. O MPT não importa cookies do
seu navegador habitual e não verifica automaticamente qual conta fez login.
Outro nome cria outro perfil manual; não existe rotação automática de contas.
Google pode impedir o login em navegadores controlados. Nesse caso, pare: não há
contorno de CAPTCHA, bloqueio, login ou cota nesta integração.

## Durante a produção

Quando uma cena precisar de imagem, o MPT abrirá o perfil e uma aba de controle
com o prompt. O preenchimento no editor é uma tentativa simples; se não aparecer,
copie o prompt da aba de controle. Não há cliques automáticos de geração.
No Flow, selecione IMAGEM, a proporção do vídeo, seu modelo e quantidade x1.
Confira os créditos/custos e as condições do serviço, gere a imagem e clique em
Download na mesma aba do projeto. Não baixe imagem antiga/outra durante a espera.
O MPT recebe o arquivo, valida o formato, salva e continua montando a cena.
Se o serviço abrir o download em outra aba em vez da aba do projeto, este
primeiro adaptador pode não recebê-lo: o comportamento real precisa de teste.

A janela de controle tem dois botões distintos:
- Flow recusou por segurança: você confirma uma recusa explícita do serviço;
  entra o mesmo card editorial identificado, sem reformular ou reenviar o pedido.
- Cancelar / limite / CAPTCHA: a tarefa para sem nova tentativa automática.

Há até 15 minutos de espera por imagem; timeout ou fechamento não provoca
reenvio. Revise o projeto antes de iniciar outra tarefa. O limite de imagens
continua contando pedidos preparados, inclusive cancelados; não mede cliques ou
créditos dentro do Flow. Escolher x2/x4 manualmente pode gerar mais imagens que
essa contagem — use x1. Downloads aprovados ficam no checkpoint da cena.

## O que continua igual

Pexels/Pixabay/Coverr alternam os candidatos, a validação visual dos bancos ainda
usa a API configurada e a geração pela API mantém seu tratamento de recusas com
cards. Selecionar Flow NÃO redireciona automaticamente pedidos recusados da API
para o Google. Falhas técnicas continuam parando a tarefa. A fila do MPT permanece
sequencial, mas este modo exige sua presença; para produção sem supervisão,
selecione o gerador por API.

Testes locais usam o navegador/Google simulados. Login, limites, disponibilidade
do modelo e download na conta real precisam ser confirmados no Windows. Este
ambiente não teve acesso à sessão do projeto do usuário.
