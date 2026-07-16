# 9. Plano de publicação

Nenhuma etapa deste plano autoriza publicação automática. Cada promoção exige aprovação explícita do proprietário.

## 1. Preparação

- fechar decisões do documento 11;
- reservar package name e Bundle ID definitivos;
- configurar contas, contratos, fiscal/bancário e papéis;
- publicar política, termos, suporte e exclusão;
- criar staging separado de produção, com banco/corpus de teste;
- concluir segurança P0/P1 e teste de restauração;
- cadastrar produtos equivalentes nas três origens de pagamento.

Gate: revisão técnica, jurídica/privacidade e comercial assinada.

## 2. Builds candidatos

- gerar frontend `dist` de commit imutável;
- gerar AAB release com upload key protegida;
- gerar archive iOS no Mac/Xcode exigido;
- produzir SBOM, checksums, release notes e matriz de configuração;
- inspecionar bundles por segredos e URLs de ambiente incorretas.

Gate: QA confirma build ↔ commit ↔ ambiente ↔ versão.

## 3. Beta Android

1. Internal testing com equipe e licenças.
2. Closed testing com público representativo.
3. Cumprir 12 testadores por 14 dias contínuos quando a conta estiver sujeita à regra.
4. Corrigir Pre-launch report, crashes, ANRs, billing e acessibilidade.

Gate: documento 5 completo, pagamentos reconciliados e suporte preparado.

## 4. Beta iOS

1. TestFlight interno.
2. Beta App Review e TestFlight externo.
3. Testar todas as regiões/storefronts e comportamento de links/pagamentos.
4. Validar conta demo, Review Notes e disponibilidade do backend.

Gate: documento 6 completo e build sem P0/P1.

## 5. Submissão

- congelar mudanças não essenciais;
- fazer backup e restore check antes da janela;
- validar políticas oficiais novamente;
- submeter metadados e builds com notas completas;
- responder aos revisores pelo canal oficial; não criar comportamento oculto para Review;
- registrar eventual rejeição como issue, corrigir causa e gerar novo build versionado.

## 6. Produção gradual

- Android: staged rollout pequeno → médio → amplo, com espera mínima definida entre etapas;
- iOS: phased release, se compatível com a estratégia;
- feature flags mantêm billing/recursos novos desligáveis por plataforma;
- monitorar login, refresh, purchase success, restore, entitlement mismatch, erro IA, p95, crash, ANR e tickets.

Critérios de pausa:

- aumento material de crash/ANR/500;
- entitlement pago não concedido ou gratuito concedido indevidamente;
- perda de sessão/conta;
- incidente de privacidade/segredo;
- degradação Railway/SQLite;
- rejeição ou aviso de política.

## 7. Pós-lançamento

- reconciliação diária de assinaturas no início;
- revisão de tickets e métricas após 24 h, 72 h, 7 e 30 dias;
- corrigir documentação/Data safety/App Privacy quando SDK ou coleta mudar;
- planejar target API anual e requisitos Xcode antes dos prazos;
- executar restore drill e revisão de acessos periodicamente.

## Responsabilidades mínimas

| Papel | Responsabilidade |
|---|---|
| Proprietário do produto | preço, mercados, marca, legal, go/no-go |
| Responsável técnico | arquitetura, segurança, builds, migrações e rollback |
| QA | matriz funcional, dispositivos, billing e evidências |
| Privacidade/jurídico | política, termos, direitos do corpus e declarações |
| Operação/suporte | monitoramento, incidentes, respostas e contas demo |

