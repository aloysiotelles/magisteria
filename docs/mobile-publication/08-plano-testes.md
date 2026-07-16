# 8. Plano de testes

## Estratégia e ambientes

- unitários: regras de conta, quota, entitlement, URL allowlist, redaction e estado de assinatura;
- integração: FastAPI + banco descartável + fakes de OpenAI/Asaas/Google/Apple;
- contrato: OpenAPI e compatibilidade de clientes móveis N e N-1;
- E2E web/mobile: staging isolado, contas e produtos sandbox;
- dispositivo: aparelhos físicos Android/iPhone, além de emuladores/simuladores;
- segurança/carga: ambiente descartável, nunca ataques à produção.

## Gates automáticos por commit

- lint/typecheck/build Python e TypeScript;
- suíte atual de 55 testes sem regressão;
- testes de migração `up` e compatibilidade de rollback;
- testes do cliente contra contrato API;
- scan de dependências, segredos e bundle;
- build web `dist`, Android debug/release e iOS em runner macOS;
- verificação de que AAB/IPA não contêm OpenAI, Asaas, Mercado Pago ou segredo de servidor.

## Casos funcionais prioritários

### Conta e sessão

- cadastro, login, logout e troca de senha;
- access token expirado, refresh, rotação concorrente, revoke-all e dispositivo perdido;
- exclusão de conta com e sem assinatura ativa;
- conta demo/review e mensagens localizadas;
- app suspenso/encerrado durante refresh e retorno após dias.

### IA e documentos

- pergunta normal e streaming; cancelar, background/foreground e rede instável;
- fontes e referências renderizadas sem HTML executável;
- roteiro DOCX e slides PPTX; timeout, retry e indisponibilidade da OpenAI;
- download, visualização, armazenamento temporário, share e limpeza;
- prevenção de duplo toque e idempotency key;
- quota em 20+ requests concorrentes: nunca executar mais trabalho pago que o reservado;
- prompt injection documental e falha/JSON inválido do revisor.

### Upload e indexação

- extensão, MIME e assinatura incompatíveis;
- limite exato e acima do limite de bytes, páginas, chunks e tempo;
- DOCX comprimido, PDF complexo, arquivo esparso, offset inválido, truncamento e upload duplicado;
- usuário comum recebe 403 em toda operação administrativa;
- reindexação em worker/fila, cancelamento, falha parcial e recuperação;
- consultas continuam disponíveis ou retornam estado degradado controlado.

### Assinaturas

Matriz por `web_asaas`, `google_play` e `apple_app_store`:

- compra inicial e evento duplicado;
- webhook antes/depois da resposta do cliente;
- evento fora de ordem;
- renovação, billing retry, grace e account hold;
- cancelamento no fim do período e revogação imediata;
- reembolso/chargeback;
- upgrade, downgrade e mudança de plano;
- restore em novo dispositivo e mesma conta;
- tentativa de vincular purchase token/transação a dois usuários;
- sandbox versus produção e replay de webhook;
- reconciliação periódica corrige evento perdido.

## Segurança

- bootstrap não cria senha conhecida; primeiro admin exige fluxo one-time;
- login/cadastro com rate limit por IP/conta e respostas não enumeráveis;
- CSRF/Origin para web; CORS exato para API;
- sessão anterior falha após troca de senha;
- HTTPS, HSTS, CSP, frame, referrer e content-type headers;
- URL externa com userinfo, subdomínio enganoso, Unicode e redirect é bloqueada;
- logs não contêm senha, token, CPF/CNPJ, email, consulta integral ou conteúdo do corpus;
- upload não segue links locais nem escapa diretório;
- WebView bloqueia HTTP, mixed content, `file://` e host fora da allowlist;
- Android backup/iOS backup não exportam tokens sensíveis.

## UX, acessibilidade e compatibilidade

- telas pequenas/grandes, orientação e safe areas;
- teclado cobrindo inputs, autocomplete correto e foco após erro;
- fonte 200%, contraste, leitor de tela, ordem de foco e alvos de toque;
- light/dark conforme decisão; reduced motion;
- offline no cold start, durante streaming, download e compra;
- botão voltar Android: fecha modal, volta rota e pede confirmação antes de sair;
- links externos retornam corretamente ao app;
- idioma pt-BR, inglês e espanhol sem overflow;
- atualização sobre versão anterior preserva sessão/dados compatíveis.

## Performance e confiabilidade

- p95/p99 de login, pergunta e streaming;
- carga concorrente de IA com limites reais/fakes;
- geração de slides fora do event loop;
- volume de 60 mil+ chunks e crescimento projetado;
- cold start, memória e tamanho do bundle;
- teste de backup e restauração com RPO/RTO medidos;
- chaos controlado: OpenAI/loja/Railway indisponível, webhook atrasado e banco read-only.

## Critérios de saída

- zero P0/P1 abertos;
- 100% dos fluxos de compra/restore aprovados por plataforma;
- crash-free e ANR dentro da meta definida pelo proprietário;
- nenhuma coleta não declarada;
- restauração de backup demonstrada;
- aprovação do proprietário para metadados, preços, política e rollout.

