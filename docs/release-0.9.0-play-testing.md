# MAGISTERIA 0.9.0 (900) — preparação para teste no Google Play

## Ordem segura de publicação

1. Fazer backup do arquivo SQLite vigente no Railway.
2. Publicar o backend `0.9.0` e aguardar as migrations `0001` a `0003`.
3. Confirmar `GET /health`, `GET /app-version`, login, consulta simples, consulta composta e histórico com duas contas de teste.
4. Executar o workflow protegido `Android signed release` no commit aprovado.
5. Baixar o artefato `magisteria-android-v0.9.0-build900` e conferir o SHA-256.
6. Na Play Console, abrir MAGISTERIA → Teste → faixa usada pelos testadores → Criar nova versão.
7. Enviar `app-release.aab`, inserir as notas de `store-assets/android/release-notes-0.9.0-pt-BR.txt` e revisar avisos do bundle.
8. Salvar como rascunho, executar a revisão pré-lançamento e somente então iniciar a distribuição aos testadores.

## Validação funcional obrigatória

- Entrar e sair; renovar sessão; excluir conta.
- Fazer `O que é oração?` e confirmar resposta proporcional.
- Fazer `Quais são os sete sacramentos?` e confirmar definição, classificação e os sete itens explicados.
- Fazer `Faça um resumo dos sete sacramentos.` e confirmar brevidade sem omissões.
- Abrir Histórico de consultas, pesquisar, ordenar, refazer, excluir um item e limpar tudo.
- Entrar com outra conta e confirmar histórico vazio/isolado.
- Repetir uma consulta equivalente e confirmar que uma nova resposta é gerada.
- Atualizar um documento de teste, reindexar e confirmar invalidação do cache.
- Testar rede indisponível, retorno Android, compartilhamento, roteiro e slides.
- Confirmar instalação, atualização e assinatura pela própria faixa de testes da Google Play.

## Assinatura do AAB

O repositório não contém upload key. O workflow espera, no GitHub Environment `google-play`:

- `ANDROID_KEYSTORE_BASE64`;
- `ANDROID_KEYSTORE_PASSWORD`;
- `ANDROID_KEY_ALIAS`;
- `ANDROID_KEY_PASSWORD`.

A upload key identifica quem pode enviar novas versões; a Play App Signing mantém a chave de assinatura distribuída aos usuários. A upload key deve ser criada fora do Git, ter cópia de recuperação protegida e nunca ser enviada por chat ou commitada.

## Rollback

- Antes da liberação: descartar o rascunho na Play Console.
- Durante teste: interromper a distribuição da versão problemática e manter a última versão estável disponível.
- Backend: reverter a aplicação sem executar o `down.sql` durante o incidente; as tabelas novas são compatíveis e não afetam clientes antigos.
- Correção Android: publicar novo bundle com `versionCode` superior a `900`; o Google Play não aceita reutilização de código de versão.
- Rollback completo das estruturas novas, em manutenção programada: aplicar os arquivos `down.sql` na ordem `0003`, `0002`, `0001`. O processo preserva as tabelas anteriores de usuários, sessões, pagamentos e documentos.

## Requisitos oficiais conferidos em 29/07/2026

- O projeto usa `targetSdk 36`, atendendo antecipadamente ao requisito do Android 16/API 36 aplicável a novos apps e atualizações a partir de 31/08/2026: https://support.google.com/googleplay/android-developer/answer/11926878?hl=pt-BR
- `versionCode 900` é maior que o build anterior e não pode ser reutilizado em upload futuro: https://developer.android.com/studio/publish/versioning
- A conta pessoal nova permanece sujeita ao teste fechado com pelo menos 12 participantes inscritos continuamente por 14 dias: https://support.google.com/googleplay/android-developer/answer/14151465
- Não foram encontrados arquivos `.so` no app ou nos plugins instalados. O projeto usa AGP 8.13.0; ainda assim, a análise automatizada do AAB e a revisão pré-lançamento da Play Console devem confirmar a compatibilidade com páginas de 16 KB: https://developer.android.com/guide/practices/page-sizes
