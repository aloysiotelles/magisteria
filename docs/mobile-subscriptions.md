# Assinaturas móveis

## Estado atual

- Asaas é o checkout de novas assinaturas web.
- Mercado Pago permanece apenas para compatibilidade legada.
- O aplicativo não exibe checkout Asaas/Mercado Pago para bens digitais.
- Nenhuma compra real de loja, produto ou segredo foi criada.

## Camada preparada

`services/subscription_service.py` normaliza:

- fontes: `free`, `trial`, `web`, `android`, `ios`;
- estados: `inactive`, `trial`, `active`, `canceled`, `expired`, `refunded`;
- acesso completo, product ID e data de renovação.

`GET /api/v1/mobile/subscription` devolve o entitlement normalizado e informa se os IDs Android/iOS foram configurados. O backend continua sendo a autoridade final de acesso.

## Variáveis reservadas

```text
GOOGLE_PLAY_PRODUCT_ID
APPLE_PRODUCT_ID
APPLE_SHARED_SECRET
GOOGLE_SERVICE_ACCOUNT_CREDENTIALS
```

Os dois IDs são identificadores públicos. Shared secret e credencial de serviço ficam somente no Railway/GitHub Environments e nunca entram no bundle.

## Google Play Billing

1. Criar assinatura e base plan no Play Console.
2. Fornecer `GOOGLE_PLAY_PRODUCT_ID`.
3. Implementar BillingClient ou uma camada como RevenueCat.
4. Enviar purchase token ao backend.
5. Validar com Google Play Developer API usando service account.
6. Persistir evento idempotente e entitlement.
7. Processar Real-time Developer Notifications.
8. Oferecer restaurar compras e gerenciar assinatura.

## Apple In-App Purchase

1. Criar subscription group e produto no App Store Connect.
2. Fornecer `APPLE_PRODUCT_ID`.
3. Integrar StoreKit 2 ou RevenueCat.
4. Enviar transação assinada ao backend.
5. Validar assinatura/JWS com App Store Server API.
6. Processar App Store Server Notifications V2.
7. Oferecer restauração e gerenciamento.

## Regras de conciliação

- Eventos são idempotentes por provedor + ID do evento/transação.
- Reembolso/chargeback remove acesso segundo a política definida.
- Cancelamento mantém acesso até o fim do período pago quando a loja assim reportar.
- O cliente nunca concede premium por conta própria.
- Não confiar em preço, status ou product ID enviados pelo dispositivo sem validação server-to-server.

## Testes futuros

- Licenças de teste Play e contas sandbox Apple.
- Compra, renovação, grace period, pausa, cancelamento, expiração, reembolso, restore e troca de dispositivo.
- Duplicidade e reordenação de webhooks/notificações.
- Conta do app diferente da conta da loja.

## Dependências externas pendentes

Contas de desenvolvedor, contratos pagos/impostos, IDs definitivos, preços, regiões, política de trials, service account Google e credenciais App Store Connect. Até isso existir, a UI deve comunicar que compras móveis ainda não estão disponíveis.

Referências: [Google Play Billing](https://developer.android.com/google/play/billing/integrate) e [Apple In-App Purchase](https://developer.apple.com/in-app-purchase/).
