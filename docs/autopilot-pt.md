# AUTOPILOT — primeira entrega: canais e recuperação

Esta entrega inicia a base prevista na `AUDITORIA_AUTOPILOT_MPT.md`. Ela permite
cadastrar canais, localizar e vincular projetos mistos salvos, manter uma fila
em SQLite e continuar a produção quando o MPT for reaberto, sem digitar UUID.

A criação de um vídeo novo apenas com título e canal, pesquisa factual,
empacotamento YouTube, AI33 de voz/SFX e publicação automática serão ligados
nas próximas entregas. O painel informa esse escopo. Ele não oferece um botão
que prometa gerar/publicar um vídeo novo enquanto essas etapas estiverem ausentes.

## Como usar

1. Feche o MPT para instalar a atualização e mantenha backup do código.
2. Mescle os arquivos do ZIP na pasta do programa; preserve `storage` e `config.toml`.
3. Abra o MPT e a seção **AUTOPILOT · Canais e recuperação automática**.
4. Cadastre nome, identificador e idioma do canal. Defina o teto ou marque
   DeepInfra sem limite, se quiser gerar novas imagens sem teto de quantidade.
5. Marque a autorização de recuperação para esse canal e salve.
6. Clique em **Localizar projetos salvos**, escolha o projeto pelo título e
   associe-o a um canal. Não é necessário informar o ID.
7. Clique em **Vincular e colocar na fila** e marque **Ativar recuperação automática**.

Ao reabrir o MPT, a fila e o botão de ativação são restaurados do disco.
Fechar somente a aba do navegador não encerra o servidor do MPT. Após reinício
completo do Windows, abra novamente o MPT ou execute `INICIAR_AUTOPILOT.bat`.
Esta entrega não instala serviço nem tarefa no Agendador do Windows.

O arquivo BAT é opcional: a interface já inicia o worker quando ativado.
Os dois caminhos compartilham um lock; abrir ambos não executa o mesmo projeto
em duplicidade. Use a mesma pasta e o mesmo usuário do Windows, com as mesmas
credenciais configuradas no MPT.

## Comportamento da recuperação

- A descoberta lê manifestos, sem copiar os gigabytes de materiais nem baixar mídia.
- O vínculo congela as opções do canal e um digest do roteiro/voz/áudio/legendas.
  A recuperação verifica novamente essa identidade antes de produzir.
- Roteiro, voz, legendas, imagens pagas, contador e Skills do projeto salvo são
  preservados. As Skills do cadastro não substituem o contexto original.
- DeepInfra ilimitado só vale quando esse é o gerador salvo. O worker não troca
  automaticamente projetos de outro gerador para DeepInfra. Novas imagens
  podem consumir saldo da conta já configurada.
- Usa a retomada existente, hashes e ledgers de imagens. Resultado pago desconhecido
  não provoca um novo envio automático.
- Tarefas remotas conhecidas ainda pendentes voltam à fila com intervalo persistente;
  projetos ocupados também aguardam, sem iniciar outra execução simultânea.
- Um processo encerrado durante a recuperação deixa um registro `running`. O lock
  do sistema operacional é liberado e o próximo worker reassume esse registro.
- Se o vídeo final já foi salvo antes da queda, o worker valida sua duração,
  decodifica áudio e vídeo com FFmpeg e registra SHA-256, sem gerar novamente.
- Um arquivo final corrompido ou parcial bloqueia o projeto para revisão. Não é
  excluído, renomeado ou sobrescrito automaticamente para contornar a proteção.
- Nenhuma função de publicação é chamada. “Vídeo recuperado” significa saída local
  decodificável; não significa QA editorial completo nem vídeo publicado.

Desativar o worker impede o próximo projeto; a operação atual pode terminar em
segurança. Desativar a autorização de um canal impede novas execuções desse canal.
Para reaplicar um novo teto a um projeto bloqueado, revise a causa e use
**Reenfileirar com as opções atuais do canal**. Isso atualiza o snapshot do
orçamento; não modifica roteiro, voz ou mídias. Repetir o vínculo não duplica jobs.

## Escopo e dados

A primeira versão suporta projetos mistos simples e projetos DeepInfra/Grok/AI33
que tenham `script.json`, plano visual e narração preservados. Projetos por
capítulos serão integrados separadamente. Google Flow não participa desse worker.
O fluxo manual existente continua disponível; não foi removido ou alterado.

Dados novos: `storage/autopilot/autopilot.sqlite3`, arquivos auxiliares SQLite e
lock do worker. O banco registra canais, snapshots sem credenciais, fila e eventos.
Não guarda chaves da API, tokens ou cópias das mídias. Mantenha banco/WAL em disco
local e faça backup com o MPT/worker encerrados ou por ferramenta SQLite apropriada.
Não apague um arquivo de lock só por existir: ele pode permanecer após liberação
normal e sua existência não indica uma execução ativa.

Os perfis iniciais são de organização e autorização de recuperação. As credenciais
continuam nas configurações existentes do MPT. Perfis completos de voz, fontes,
publicação e credenciais independentes por canal pertencem à próxima etapa.
Não há execução concorrente entre canais enquanto o pipeline depender de config global.

## Estabilização dos testes da auditoria

- Os dois fixtures históricos de fingerprints foram corrigidos para excluir o
  novo flag de execução `mixed_deepinfra_unlimited`, assim como já excluíam o
  equivalente Grok. A política de fingerprint de produção não foi relaxada.
- Os testes do módulo de imagens Codex passaram a refletir a política já vigente:
  a entrada de nova geração está bloqueada. Testes de transporte de geração que
  não existe mais foram substituídos por verificações do bloqueio antes da rede;
  testes de parsing, limites, streams truncados, credenciais e diagnóstico foram
  mantidos/adaptados para testar diretamente suas funções atuais.
- Nenhuma geração Codex foi reativada e não foram usados skips/xfails para ocultar
  as falhas apontadas na auditoria.

## Validação desta entrega

Os testes novos exercitam snapshots de canal, duplo clique, troca de canal,
pausa, concorrência de workers, encerramento real de processo, recuperação do
registro persistido, espera remota, mudança de roteiro/áudio, proteção de
materiais, ausência de publicação e de nova narração, FFmpeg real e o painel
Streamlit. Os provedores pagos são simulados; não houve geração ou upload real.

O painel também é conferido em Chromium. Homologação de chamadas pagas e do
comportamento no Windows real permanece necessária no computador de produção.

Validação ampliada registrada: 589 testes aprovados e cinco ignorados na seleção
de 32 módulos da auditoria e do AUTOPILOT; verificações adicionais de recuperação
e interface também passaram após os últimos ajustes. Testes ignorados exigem
contas pagas ou Redis real. A instalação Windows ainda precisa ser homologada
no computador de produção.
