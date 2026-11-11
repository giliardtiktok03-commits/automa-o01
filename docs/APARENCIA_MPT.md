# Aparência do MPT: claro, escuro e sistema

O botão **Aparência**, no topo do aplicativo, oferece:

- **Claro**: fundo claro, preservado como padrão inicial.
- **Escuro**: fundos escuros e textos/controles com contraste ajustado.
- **Seguir o sistema**: acompanha a preferência de cor do navegador/sistema,
  inclusive quando ela muda com a página aberta.

A troca se aplica durante o rerun normal da interface, sem reiniciar o servidor.
A escolha fica em `[ui].appearance_theme` do `config.toml` existente. Ao abrir uma
nova sessão, ela é restaurada. A preferência é da instalação; não é uma identidade
individual de usuário. A sessão aberta mantém sua escolha atual.

O salvamento usa as funções não bloqueantes do MPT. Durante uma geração que
ocupe o lock de configuração, a gravação no disco poderá ser adiada até a liberação,
como nas demais preferências existentes; a mudança visual na sessão é imediata.

## Instalação no Windows

1. Feche o servidor do MPT e faça backup do código, de `config.toml` e de `storage`.
2. Extraia o ZIP na raiz do MPT, mesclando as pastas e substituindo os arquivos
   correspondentes. Não apague suas configurações nem os arquivos de produção.
3. Reabra o MPT e escolha **Aparência → Tema do aplicativo → Escuro**.

O ZIP é cumulativo com a versão Historical Documentary Director, AUTOPILOT e
DeepInfra sem teto. Não leva configurações, credenciais, tarefas nem vídeos.

## Mudanças e limites

- `webui/appearance.py`: seletor, normalização e preferência persistente.
- `webui/appearance.css`: paletas e estilos de apresentação para a versão
  Streamlit 1.66.1 fixada no projeto; menus, formulários, janelas e cabeçalhos.
- `webui/Main.py`: aplica o tema, oferece o botão no topo e adapta o seletor de
  fontes de materiais e os cabeçalhos coloridos. A numeração/cor dos módulos
  existentes é mantida, com contraste apropriado para o fundo.
- `test/services/test_webui_appearance.py`: troca/restauração da preferência e
  recuperação de valores inválidos sem alterar opções de vídeo.

Não há inversão de imagens ou filtro aplicado ao aplicativo inteiro: fotos,
vídeos e cores escolhidas para legendas/thumbnails são preservados. O tema não
altera roteiro, Skill, provedor, fila ou configurações de renderização. Não muda
opções globais internas do Streamlit nem escreve sua configuração de servidor.
Gráficos ou interfaces de terceiros incorporadas podem ter sua própria aparência.
Atualizações futuras do Streamlit devem revalidar os seletores CSS.

Esta entrega acrescenta o controle de aparência ao layout atual. A reorganização
completa por módulos e a concentração de controles de cada Skill são outra etapa;
não são declaradas como concluídas por esta atualização de tema.

Validação: testes automatizados de preferência/configuração, inicialização,
configurações, Skills/AUTOPILOT e seletor agrupado de materiais; Chromium com troca
claro/escuro, acompanhamento do sistema, restauração após recarga, janelas de
configuração e capturas em desktop e celular. Sem chamadas de geração pagas.

Os 19 testes selecionados passaram. Um filtro antigo de widgets no teste do
seletor agrupado falhava também na versão anterior quando encontrava um campo sem
chave explícita; ele foi corrigido para tolerar `key=None`, mantendo as verificações
de fonte, visibilidade e valores de concorrência.
