# Diagnóstico LOC e modo independente — 10/11/2026

## Evidência da tarefa informada

Tarefa `d2e0740c-6aba-4fdd-8635-8b187dcb0836`: áudio externo e legendas
Whisper concluídos. A etapa histórica durou 4,22 segundos e terminou sem material
aprovado, com geradores desativados ou não configurados. O log antigo não contém
status HTTP, contagem de resultados ou classificações de direitos. Esse projeto
Windows não está neste ambiente; não é possível atribuir sua falha a uma API específica.

## Correções verificadas

- Modo somente pesquisa antes das etapas de produção, sem exigir fontes de vídeo.
- Botão independente para testar LOC, sem projeto, áudio ou geração de IA.
- Resultados vazios deixam de aparecer como disponibilidade de materiais.
- Registro de requisições e status HTTP por serviço, resultados, direitos,
  disponibilidade de IIIF/OCR e download/extração.
- Materiais liberados são entregues ao pipeline com registro de seleção e arquivo.
- Fallback de bancos configurados também em cenas planejadas como imagem quando
  a pesquisa histórica está ativa. Nenhum provedor desativado é ligado automaticamente.
- Falha final com motivos por cena e caminho do diagnóstico, sem suprimir a falha.
- Direitos desconhecidos continuam excluídos da aprovação e do download.

Foram reproduzidos em testes o desvio de somente pesquisa para produção e a omissão
de bancos configurados em cenas planejadas como imagem. Não se afirma que ambos
ocorreram na tarefa original, cujas configurações não foram fornecidas.

## Resultado da consulta real neste ambiente

Consulta: `Dust Bowl Farm Security Administration`.

| Serviço | Resultado | Pedidos | HTTP da API |
|---|---|---:|---|
| JSON/metadados | Falhou: ProxyError na conexão | 1 | Nenhuma resposta da origem |
| IIIF/imagens | Não testado | 0 | Nenhum |
| Texto/OCR | Não testado | 0 | Nenhum |

O proxy do ambiente bloqueou a conexão. Isso não demonstra indisponibilidade da LOC.
A verificação real das três APIs continua pendente na rede do usuário. O relatório
não transforma falha de proxy em status HTTP da LOC.

## Validação

432 testes passaram, 3 foram ignorados e 20 subtestes passaram. Fixtures verificam
as três APIs com JSON, IIIF e ALTO, ausência de resultados, direitos desconhecidos,
falha de conexão, interface independente, passagem de materiais e fallback.
Nenhuma geração paga foi executada. Testes simulados não substituem a validação real.

## Arquivos

Novos: `app/services/historical_archive/diagnostics.py`, `research_mode.py` e
`test/services/test_archive_diagnostics.py`.

Alterados: `app/services/historical_archive/{contracts,downloader,network,service}.py`,
`app/services/historical_archive/providers/{loc,loc_services}.py`,
`app/services/mixed_materials.py`, `app/services/task.py`, `webui/Main.py`,
`webui/historical_archive_settings.py`, `test/services/test_mixed_materials.py`
e a documentação e os pacotes Windows.

## Instalação e rollback

Feche o MPT, faça backup e extraia o ZIP na raiz da instalação. O pacote não inclui
config.toml real, storage ou .venv. Reabra webui.bat. O módulo começa desativado em
instalações novas; configurações existentes são preservadas. Para rollback, feche o
MPT e restaure os arquivos de código do backup, preservando storage e configurações.
