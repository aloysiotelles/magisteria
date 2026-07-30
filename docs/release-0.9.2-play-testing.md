# MAGISTERIA 0.9.2 (902) — atualização para teste no Google Play

## Ordem segura

1. Confirmar antes do deploy que `MAGISTERIA_Dogmas_Catolicos_Base_RAG.md` está ativo, com 1.194 documentos, 72.247 trechos e indexação em 100%.
2. Publicar o backend 0.9.2 e confirmar `/health` e `/app-version`.
3. Confirmar novamente os mesmos totais e que o documento de dogmas continua ativo e recuperável.
4. Testar uma resposta catequética, uma formação, uma homilia e uma consulta sem passagem direta.
5. Confirmar linguagem natural, cobertura integral, fontes moderadas e ausência de metalinguagem técnica na resposta.
6. Gerar e verificar o AAB assinado `0.9.2 (902)`.
7. Enviar o AAB à mesma faixa de teste fechado e usar `store-assets/android/release-notes-0.9.2-pt-BR.txt`.
8. Revisar os avisos da Play Console e disponibilizar a atualização aos testadores.

## Rollback

- Antes da liberação, descartar a versão em rascunho na Play Console.
- Durante o teste, interromper a distribuição e manter o build 901 disponível.
- Uma correção Android deve usar `versionCode` superior a 902.
- O deploy não limpa, substitui nem reindexa manualmente o volume documental.
