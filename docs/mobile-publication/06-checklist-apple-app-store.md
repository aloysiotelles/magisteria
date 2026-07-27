# 6. Checklist Apple App Store

Data de referência: 16/07/2026. Revalidar App Store Connect e guidelines no dia da submissão.

## Conta e identidade

- [ ] Apple Developer Program ativo no titular correto.
- [ ] Agreements, Tax and Banking concluídos para In-App Purchase.
- [ ] Definir Bundle Identifier definitivo e App ID explícito.
- [ ] Criar registro no App Store Connect, nome, SKU, categoria e disponibilidade.
- [ ] Confirmar trader status/DSA se houver distribuição na União Europeia.
- [ ] Definir usuários, papéis e autenticação forte; não compartilhar credenciais pessoais.

## Ambiente, certificados e build

- [ ] Mac controlado ou CI macOS disponível; Windows não gera/assina o archive iOS.
- [ ] Desde 28/04/2026, uploads precisam de **Xcode 26+ e SDK iOS 26+**, conforme [Upcoming Requirements](https://developer.apple.com/news/upcoming-requirements/).
- [ ] Definir deployment target a partir de suporte desejado e Capacitor; não confundir deployment target com SDK de build.
- [ ] Configurar certificado de distribuição e App Store provisioning profile; guia: [criar profile de distribuição](https://developer.apple.com/help/account/provisioning-profiles/create-an-app-store-provisioning-profile/).
- [ ] Habilitar somente capabilities necessárias (IAP, associated domains, push se aprovado).
- [ ] Version e build number monotônicos; archive ligado ao commit e ambiente.
- [ ] Upload via Xcode/Transporter conforme [documentação de builds](https://developer.apple.com/help/app-store-connect/manage-builds/upload-builds/).
- [ ] Privacy manifest/required-reason APIs de todos os SDKs revisados.

## Pagamentos e assinatura

- [ ] Criar subscription group e produtos auto-renováveis no App Store Connect.
- [ ] Usar StoreKit 2 para liberar assinatura/recursos digitais; a [App Review Guideline 3.1](https://developer.apple.com/app-store/review/guidelines/) disciplina IAP e exceções por categoria, entitlement, região e storefront.
- [ ] Implementar restore purchases e tela “Gerenciar assinatura”.
- [ ] Backend valida transações e processa App Store Server Notifications/API.
- [ ] Testar sandbox/TestFlight: compra, renovação acelerada, billing retry, grace, revoke, refund, upgrade/downgrade e expiração.
- [ ] Não exibir checkout Asaas/Mercado Pago no build iOS global por padrão.
- [ ] Se optar por app companion para assinantes web, não incluir compra nem CTA externo fora das permissões da storefront; documentar a decisão para Review.
- [ ] Se usar external purchase link, obter entitlement e implementar regras por storefront; uma permissão dos EUA não deve ser generalizada.

## Conta, privacidade e revisão

- [ ] Política de privacidade pública e link dentro do app.
- [ ] Preencher App Privacy considerando OpenAI, pagamentos, analytics/crash e quaisquer SDKs; consultar [App Privacy Details](https://developer.apple.com/app-store/app-privacy-details/).
- [ ] Como há criação de conta, permitir iniciar a exclusão **dentro do app**; ver [orientação oficial de account deletion](https://developer.apple.com/support/offering-account-deletion-in-your-app/).
- [ ] Explicar relação entre exclusão e assinatura Apple: orientar cancelamento sem dificultar a solicitação de deleção.
- [ ] Criar conta demo funcional, dados de teste e notas precisas para App Review.
- [ ] Backend e serviços devem estar disponíveis durante a revisão.
- [ ] Fornecer contato técnico e comercial que responda ao Review.
- [ ] Responder ao questionário etário atualizado de 2026; classificação é obrigatória.

## Valor móvel e guideline 4.2

- [ ] Demonstrar que não é apenas um site: UI empacotada, offline/error state, secure session, share, arquivos, deep links, safe areas, back/navigation e integração de compras.
- [ ] Capturas e Review Notes descrevem essas capacidades.
- [ ] Não apontar a WebView principal diretamente para o Railway.
- [ ] Links externos abrem em contexto seguro e com allowlist.

## Metadados e assets

- [ ] Nome e subtítulo dentro dos limites do App Store Connect.
- [ ] Descrição, keywords, promotional text e notas de assinatura corretas.
- [ ] Support URL, Marketing URL opcional e Privacy Policy URL.
- [ ] Ícone 1024×1024 sem transparência problemática e assets gerados pelo Xcode.
- [ ] Screenshots nos tamanhos/plataformas requeridos; conferir [especificações atuais](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications).
- [ ] Declaração de content rights para documentos/corpus e material de terceiros.
- [ ] Permissões com `Info.plist` purpose strings claras e coerentes.

## TestFlight e submissão

- [ ] TestFlight interno com equipe e contas sandbox.
- [ ] TestFlight externo após Beta App Review, com descrição e feedback contact.
- [ ] Testar iPhone pequeno/grande, iPad apenas se declarado, orientação, fonte ampliada, VoiceOver, dark mode decidido, teclado e safe areas.
- [ ] Testar cold start, atualização, expiração de token, offline, compra/restore, arquivos e retorno de browser.
- [ ] Executar validação do archive, scan de segredos e verificação de símbolos/crash reporting.
- [ ] Submeter com Review Notes, demo account e instruções de IA/assinatura.
- [ ] Usar phased release e gates do documento 9.

