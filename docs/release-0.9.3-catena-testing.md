# MAGISTERIA 0.9.3 (903) — Catena Áurea nas consultas evangélicas

## Ordem segura de publicação

1. Confirmar a suíte Python, a suíte móvel e o bundle Android.
2. Publicar o backend 0.9.3 no Railway sem limpar nem substituir o volume documental.
3. Aguardar a reindexação automática restrita à Catena e confirmar em `/status` que `catena_aurea.documentos >= 1`, `catena_aurea.trechos > 0` e `indexing_version = catena-structured-1`.
4. Validar `/health`, `/app-version` e os totais gerais do acervo.
5. Executar consultas de fumaça sobre Mt 5,1-12, filho pródigo, multiplicação dos pães, Paixão, Emaús e Lázaro, além da consulta não evangélica sobre a Imaculada Conceição.
6. Confirmar na telemetria que a busca Catena ocorreu antes da busca complementar e que não houve atribuição patrística inventada.
7. Gerar o AAB assinado 0.9.3 (903), enviar à faixa já existente de testes e usar as notas `store-assets/android/release-notes-0.9.3-pt-BR.txt`.

## Migração e rollback

- A migração `0002_catena_chunk_metadata_isolation` cria apenas a tabela auxiliar `catena_chunk_metadata` e seus índices; o nome específico evita colisões com tabelas legadas e há um rollback correspondente.
- Na primeira inicialização, somente o arquivo da Catena é resegmentado para a versão `catena-structured-1`; os demais documentos inalterados são reutilizados.
- A versão da política invalida entradas antigas do cache sem apagar histórico, usuários, assinaturas ou documentos.
- Em rollback, publicar a versão anterior do backend. Não limpar o volume e não reduzir o `versionCode` de um AAB já enviado.
