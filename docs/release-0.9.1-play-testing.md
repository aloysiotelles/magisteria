# MAGISTERIA 0.9.1 (901) — atualização para teste no Google Play

## Ordem segura

1. Fazer backup do SQLite de produção.
2. Publicar o backend 0.9.1 e confirmar `/health` e `/app-version`.
3. Configurar no backend as credenciais OAuth do Gmail usadas pelo remetente atual.
4. Testar “Esqueci minha senha” com conta existente e inexistente; a mensagem pública deve ser igual.
5. Confirmar que o token expira, funciona uma única vez e encerra sessões anteriores sem alterar assinatura ou cobrança.
6. Testar uma lista curta e uma longa, confirmando que nenhum item canônico foi omitido.
7. Gerar e verificar o AAB assinado `0.9.1 (901)`.
8. Enviar o AAB à mesma faixa de teste e usar `store-assets/android/release-notes-0.9.1-pt-BR.txt`.
9. Revisar os avisos da Play Console e disponibilizar aos testadores somente após a aprovação do backend.

## Rollback

- Antes da liberação, descartar a versão em rascunho na Play Console.
- Durante o teste, interromper a distribuição e manter o build 900 disponível.
- Uma correção Android deve usar `versionCode` superior a 901.
- As novas estruturas de recuperação de senha são aditivas e não modificam tabelas de assinatura ou cobrança.
