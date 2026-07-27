# 10. Plano de rollback

## Princípios

- Lojas não permitem simplesmente reinstalar um binário de versão inferior. O retorno normalmente exige pausar rollout e, se necessário, publicar um **novo build com número maior** contendo a versão conhecida como boa.
- Backend deve permanecer compatível com app móvel N-1 durante a janela definida.
- Migrações de dados devem ser expand/contract; não fazer downgrade destrutivo.
- Entitlements e eventos financeiros nunca são “desfeitos” apagando registros; são reconciliados e auditados.

## Preparação obrigatória

- tag/commit, checksum e artefato do último release conhecido como bom;
- feature flags e kill switch por plataforma/versão;
- backup consistente e restauração testada;
- migrations com plano de forward-fix;
- dashboards/alertas e responsáveis on-call;
- mensagem de manutenção e canal de suporte prontos.

## Cenários

### Falha exclusiva do cliente

1. pausar staged/phased rollout;
2. desligar a funcionalidade por flag, se possível;
3. manter API compatível;
4. preparar novo build de versionCode/build maior a partir do release bom mais correção mínima;
5. testar e submeter como expedited review somente se elegível e necessário.

Usuários que já instalaram o build ruim continuam existindo; o backend precisa oferecer degradação segura ou bloqueio de versão com instrução clara.

### Falha de backend/API

1. desativar feature nova;
2. reverter aplicação somente se schema permanecer compatível;
3. caso contrário, aplicar forward-fix;
4. preservar webhooks em fila/retry e não perder eventos;
5. validar health, login, IA e entitlement antes de reabrir.

### Migração de banco com problema

- parar writers afetados via feature flag/manutenção;
- não executar `DROP`/rollback cego;
- restaurar somente com aprovação de incidente e avaliação de eventos ocorridos depois do backup;
- preferir correção forward e backfill idempotente;
- reconciliar Google, Apple e Asaas após recuperação.

### Erro de pagamentos/entitlement

- desligar novas compras, não o acesso legítimo existente;
- manter ledger de eventos e respostas originais protegidas;
- reconciliar provider-side;
- conceder acesso temporário controlado quando necessário para evitar prejuízo;
- comunicar usuários afetados e registrar ajustes/reembolsos.

### Incidente de segredo ou privacidade

- revogar/rotacionar chave, token e sessão;
- preservar evidência e restringir acesso a logs;
- remover build de venda/distribuição apenas conforme decisão de incidente;
- avaliar notificação legal e às lojas;
- publicar build limpo e atualizar declarações de dados.

## Verificação pós-rollback

- health e erro 5xx;
- autenticação e refresh;
- compra, restore e entitlement;
- perguntas/streaming e geração de documentos;
- consistência do banco e fila de webhooks;
- tickets/crash/ANR;
- confirmação de que nenhuma versão incompatível continua sendo promovida.

## Encerramento

O incidente só termina após causa raiz, dados reconciliados, métricas estáveis, comunicação concluída e ação preventiva com proprietário/prazo.

