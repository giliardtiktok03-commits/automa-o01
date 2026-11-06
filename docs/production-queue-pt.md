# Fila sequencial e etapas coloridas

1. Configure tema, roteiro, áudio e demais opções do primeiro vídeo.
2. Clique em Gerar vídeo: ele começa em segundo plano.
3. Prepare os campos do próximo vídeo e substitua o áudio enviado, se houver.
4. Clique em Adicionar próximo vídeo à fila. Repita para os outros vídeos.
5. A seção Fila de produção lista itens e progresso. Ver tarefa abre o resultado
   ou os logs daquele item. O gerenciador de tarefas conserva o acesso ao histórico.

Só um vídeo da WebUI é gerado por vez. Os próximos começam automaticamente,
inclusive depois de uma falha. Cada envio copia roteiro, parâmetros, arquivos
preparados e configurações de provedores daquele momento; editar o próximo não
altera um item enviado. Chaves copiadas ficam somente na memória do processo.
Envios idênticos ainda ativos podem ser agrupados para evitar trabalho duplicado.

Mantenha o MPT e o computador ligados, sem suspensão. Fechar a aba não encerra o
servidor local, mas fechar seu terminal, reiniciar o MPT ou desligar o PC perde a
fila em memória. Não há retomada automática da fila após reinício. Arquivos de
vídeos concluídos e checkpoints existentes continuam em storage/tasks.

As cores e números identificam as etapas: 01 roteiro roxo, 02 vídeo azul,
03 áudio âmbar, 04 legendas verde e 05 fila verde-petróleo. Os nomes permanecem
visíveis, sem depender só da cor. A fila não reduz o tempo de renderização de
cada vídeo e não introduz renderização paralela. APIs utilizadas continuam com
suas cobranças normais por vídeo; adicionar à fila autoriza a execução do item.
