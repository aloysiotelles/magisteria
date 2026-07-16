# Publicação Apple App Store

## Requisitos técnicos atuais

Desde 28/04/2026, uploads precisam de Xcode 26+ e SDK iOS 26+: [Apple Upcoming Requirements](https://developer.apple.com/news/upcoming-requirements/). O projeto define deployment target iOS 15 e usa Swift Package Manager.

Este Windows não possui Xcode; criação e sincronização estrutural foram concluídas, mas compilação, assinatura, simulador e upload iOS não foram executados localmente.

## Build em Mac

Pré-requisitos: macOS compatível, Xcode 26+, Node 22+, pnpm 11.9 e conta Apple Developer.

```bash
pnpm install --frozen-lockfile
pnpm build:web
pnpm cap:sync:ios
pnpm cap:ios
```

O script pós-sync reescreve caminhos SPM para symlinks portáveis do pnpm. No Xcode:

1. Selecione o Team.
2. Troque o bundle ID placeholder.
3. Verifique `PrivacyInfo.xcprivacy` no target App.
4. Execute em iPhone e iPad.
5. Archive com configuração Release.
6. Validate App e distribua para TestFlight.

## Configuração existente

- `CFBundleShortVersionString`: 0.8.0.
- `CFBundleVersion`: 1.
- iOS 15+.
- Retrato em iPhone/iPad e full screen.
- ATS sem carga arbitrária.
- Declaração de criptografia não isenta: falsa, usando apenas APIs padrão do sistema/HTTPS; confirmar no processo jurídico/export compliance.
- Privacy manifest declara File Timestamp/C617.1 exigido pelo Filesystem.
- Nenhuma permissão de câmera, microfone, localização ou fotos.

## App Store Connect

- App record com bundle ID definitivo e SKU.
- Contratos, dados bancários e fiscais.
- Nome/subtítulo, descrição, keywords, categoria e copyright.
- Support URL, Marketing URL opcional e Privacy Policy URL.
- Screenshots obrigatórios nas dimensões atuais aceitas.
- App Privacy coerente com os dados realmente coletados.
- Age Rating atualizado.
- Conta e instruções para App Review.
- Fluxo demonstrável de exclusão dentro do app.
- Produtos/subscription group antes de habilitar IAP.

## TestFlight

1. Internal Testing.
2. External Testing após Beta App Review.
3. Testar iOS 15 e iOS 26, tamanhos pequenos/grandes, iPad, teclado, safe areas e rede instável.
4. Exercitar sandbox IAP somente depois dos IDs reais.

## Revisão e compras

Serviços digitais dentro do app devem usar In-App Purchase segundo as [App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/), respeitando somente exceções/storefronts oficialmente aplicáveis. O app atual não inicia compra web.

## Rollback

Remover o build do TestFlight ou pausar phased release. Para produção, publicar correção com `CFBundleVersion` maior; preservar compatibilidade da API com versões instaladas.
