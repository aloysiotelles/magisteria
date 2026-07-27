# 5. Checklist Google Play

Data de referência: 16/07/2026. Políticas mudam; revalidar no Play Console no dia de cada submissão.

## Conta e identidade

- [ ] Conta Google Play Console ativa, titular legal, contato e verificação concluídos.
- [ ] Confirmar se a conta pessoal foi criada após 13/11/2023. Nesse caso, a regra oficial exige teste fechado com pelo menos 12 testadores por 14 dias contínuos antes de solicitar acesso à produção: [requisitos de teste para novas contas pessoais](https://support.google.com/googleplay/android-developer/answer/14151465?hl=en-EN).
- [ ] Definir package name definitivo, por exemplo `br.com.DOMINIO.magisteria`; ele é único e não deve ser improvisado.
- [ ] Definir nome público, categoria, países, preço do app e contato do desenvolvedor.
- [ ] Verificar status de comerciante, fiscal, bancário e perfil de pagamentos quando aplicável.

## Build e assinatura

- [ ] Projeto Capacitor Android reproduzível, sem `server.url` de produção.
- [ ] Gerar **Android App Bundle (AAB)** release; conferir [criação e configuração do app](https://support.google.com/googleplay/android-developer/answer/9859152?hl=en).
- [ ] Ativar Play App Signing e proteger a upload key separadamente; seguir a [documentação de chaves e assinatura](https://support.google.com/googleplay/android-developer/answer/9842756?hl=en-GB).
- [ ] Guardar keystore/upload key fora do Git, com backup e responsáveis definidos.
- [ ] Definir versionCode monotônico e versionName rastreável ao commit.
- [ ] Target API: em 16/07/2026 o prazo publicado determina **Android 16/API 36 a partir de 31/08/2026**, com extensão possível até 01/11/2026. Como a publicação ocorrerá próximo ou após o prazo, construir já com API 36; ver [requisitos oficiais de target API](https://support.google.com/googleplay/android-developer/answer/11926878?hl=en).
- [ ] Definir minSdk com base em telemetria/mercado e compatibilidade do Capacitor, não por palpite.

## Pagamentos e assinatura

- [ ] Criar produtos/subscrições e base plans no Play Console.
- [ ] Para recursos digitais/IA, usar Play Billing no fluxo padrão. A política proíbe conduzir o usuário a pagamento externo por WebView, botão, link, mensagem ou UI, salvo programas/exceções aplicáveis: [política de pagamentos](https://support.google.com/googleplay/android-developer/answer/9858738?hl=en).
- [ ] Não exibir checkout Asaas/Mercado Pago no build Android por padrão.
- [ ] Avaliar programas de alternative billing/external content **por país e elegibilidade**, com revisão jurídica e inscrição; não assumir que uma exceção global existe.
- [ ] Enviar purchase token ao backend, validar antes do entitlement e reconhecer compras conforme a [integração Play Billing](https://developer.android.com/google/play/billing/integrate).
- [ ] Configurar Real-time Developer Notifications e reconciliação server-side.
- [ ] Testar compra, renovação, pendência, cancelamento, grace, pause, restore, reembolso, chargeback e expiração.

## Política, dados e conta

- [ ] URL HTTPS pública da política de privacidade, dentro do app e na ficha.
- [ ] Preencher Data safety com dados do app e SDKs de terceiros; guia oficial: [Data safety](https://support.google.com/googleplay/android-developer/answer/10787469?hl=en).
- [ ] Se o app cria conta, oferecer exclusão dentro do app e link web funcional informado no Play Console: [requisito de exclusão](https://support.google.com/googleplay/android-developer/answer/13327111?hl=en).
- [ ] Explicar retenção legal, deleção de consultas/diagnósticos/documentos e cancelamento da assinatura.
- [ ] Declarar anúncios como “não” se confirmado; se houver SDK/publicidade, declarar com precisão.
- [ ] Preencher classificação indicativa e público-alvo; revisar conteúdo religioso/educacional e IA.
- [ ] Preencher App access e fornecer credenciais de demonstração estáveis para áreas autenticadas.
- [ ] Declarar permissões; solicitar somente arquivo/câmera/notificação se realmente usadas e no momento da necessidade.

## Ficha da loja

- [ ] Ícone 512×512 conforme Play Console.
- [ ] Feature graphic 1024×500 e assets sem alegações enganosas; ver [requisitos de preview assets](https://support.google.com/googleplay/android-developer/answer/9866151?hl=en).
- [ ] Capturas reais de telefone, nos idiomas publicados, mostrando valor móvel.
- [ ] Descrição curta, descrição completa e notas de assinatura/IA.
- [ ] E-mail de suporte monitorado e site/URL de suporte.
- [ ] Política, termos e página de exclusão acessíveis sem login.

## Testes e submissão

- [ ] Internal testing com contas de licença e billing sandbox.
- [ ] Closed testing em aparelhos e versões variadas; cumprir 12/14 dias se aplicável.
- [ ] Pre-launch report sem crash, ANR, problemas de acessibilidade ou segurança bloqueadores.
- [ ] Testar offline, atualização, deep links, botão voltar, upload/download/share, fontes grandes e interrupção de processo.
- [ ] Validar que nenhuma chave/segredo está no AAB.
- [ ] Criar release notes e plano de suporte.
- [ ] Produção em staged rollout com critérios de pausa e rollback do documento 10.

