# Checklist de release móvel

## Identidade e versão

- [ ] Proprietário confirmou app name, bundle/application ID e titular legal.
- [ ] Placeholder `br.com.seudominio.magisteria` removido de Capacitor, Android e Xcode.
- [ ] `package.json`, `APP_VERSION`, Android `versionName` e iOS marketing version representam a mesma versão pública.
- [ ] Android `versionCode` e iOS `CFBundleVersion` foram incrementados.
- [ ] `CHANGELOG.md` atualizado.

## Build e qualidade

- [ ] `python -m pytest -q`.
- [ ] `pnpm build`, `typecheck`, `lint`, `test:mobile`, `build:web`.
- [ ] `pnpm audit --audit-level high` sem high/critical não aceito.
- [ ] `pnpm cap:sync` sem mudanças inesperadas; `Package.swift` portátil.
- [ ] Android `bundleRelease`, lint e unit tests.
- [ ] iOS simulator build e Archive Xcode 26+.
- [ ] Diff revisado; sem `.env`, token, keystore, certificado ou profile.

## Funcional

- [ ] Web Railway continua saudável.
- [ ] Cadastro, login, persistência, refresh, logout e troca de senha.
- [ ] Pergunta, streaming, fontes, quotas e mensagens da IA.
- [ ] Offline, reconexão, timeout, 401 e falha Railway.
- [ ] Duplo toque não duplica operação.
- [ ] Roteiro/slides abrem e compartilham.
- [ ] Upload administrativo permitido/negado corretamente.
- [ ] Links externos usam Browser e host estranho é bloqueado.
- [ ] Exclusão de conta e retorno ao login.
- [ ] Safe areas, teclado, voltar, telas pequenas, tablet, VoiceOver/TalkBack.

## Segurança e privacidade

- [ ] Administrador de produção usa senha rotacionada e bootstrap foi removido do Railway.
- [ ] `COOKIE_SECURE=true`, CORS e rate limit ativos.
- [ ] Política/termos/suporte definitivos publicados em HTTPS.
- [ ] Data Safety e App Privacy conferem com o comportamento real.
- [ ] Privacy manifest incluído no target iOS.
- [ ] Android manifesta somente permissões necessárias.
- [ ] Conta de revisão não é administradora.

## Pagamentos

- [ ] Checkout web oculto no mobile.
- [ ] IDs Play/Apple fornecidos e ambientes sandbox testados antes de ativar compra.
- [ ] Backend valida transações e webhooks/notificações idempotentes.
- [ ] Restore, cancelamento, expiração, reembolso e grace period testados.
- [ ] Termos comerciais e preços aprovados.

## Lojas

- [ ] Ícone, screenshots, descrições, categoria e classificação.
- [ ] Support URL, Privacy URL e Account Deletion URL.
- [ ] Play testing requirement concluído, se aplicável.
- [ ] AAB assinado e Play App Signing.
- [ ] TestFlight interno/externo aprovado.
- [ ] Rollout gradual e responsáveis de monitoramento definidos.

## Rollback

- [ ] Backend é compatível com versão anterior.
- [ ] Feature flags/kill switches documentados para recursos arriscados.
- [ ] Responsável pode pausar rollout nas duas lojas.
- [ ] Correção usa build number superior.
- [ ] Backup/restore do banco foi testado fora de produção.

## Pendências atuais do proprietário

- Identificador definitivo, organização e contato de suporte.
- Textos jurídicos definitivos e URLs públicas.
- Contas Google/Apple, contratos, impostos e dados bancários.
- Keystore/certificados/profiles mantidos fora do Git.
- Produtos/preços/trials e política de assinatura.
- Mac com Xcode 26 ou execução bem-sucedida do job iOS.
