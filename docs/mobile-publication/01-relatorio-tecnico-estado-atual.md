# 1. Relatório técnico do estado atual

Data do diagnóstico: 16/07/2026  
Repositório: `magister-ia`  
Commit analisado: `14c1c8115d4586318ddb15d6930041785fc6a972`  
Ambiente de produção: somente leitura; nenhuma configuração ou dado foi alterado.

## Resumo executivo

O MagisterIA pode ser levado às lojas sem reconstrução do backend, da inteligência artificial ou das regras de negócio. Contudo, o frontend atual **não pode ser entregue diretamente ao Capacitor**: ele é uma página Jinja renderizada pelo FastAPI, usa rotas relativas e não possui uma pasta de artefatos web compilados com um `index.html` autônomo. O caminho sustentável é extrair uma camada cliente empacotável e consumir uma API versionada no Railway.

A produção está funcional e respondeu em 16/07/2026:

- `/health`: HTTP 200, versão 0.8.0;
- `/status`: HTTP 200, 1.107 documentos e 60.422 chunks, indexação concluída;
- `/versao`: HTTP 200.

Esses números são uma fotografia do momento, não uma garantia contratual. Não foram feitas chamadas autenticadas, uploads, pagamentos ou mutações.

## Stack e estrutura

| Área | Estado verificado |
|---|---|
| Linguagem/backend | Python 3.12, FastAPI, Uvicorn |
| Frontend | Jinja2 em `templates/index.html`, JavaScript e CSS sem framework em `static/` |
| Build do frontend | Inexistente; não há `dist/`, `build/` ou pipeline SPA. O script chamado `build` apenas executa `compileall` do Python |
| Hospedagem | Imagem Docker no Railway, health check `/health`, Uvicorn, volume persistente recomendado em `/data` |
| Dados transacionais | SQLite em `APP_DATABASE_FILE`, padrão `banco_vetorial/magisteria.sqlite` |
| Índice documental | Segundo arquivo SQLite/FTS5 apontado por `INDEX_FILE`, apesar do nome padrão `indice.json` |
| Documentos | Diretório configurável por `DOCUMENTS_DIR`; no Railway, a documentação orienta `/data/Documentos` |
| IA | OpenAI API para resposta RAG, revisão de resposta, roteiros e slides/imagens |
| Autenticação web | Sessão opaca server-side em cookie `magisteria_session`, duração de 30 dias, `HttpOnly`, `SameSite=Lax`; sem JWT |
| Pagamentos novos | Asaas é o provedor ativo do fluxo de assinatura |
| Pagamento legado | Código e webhook de Mercado Pago permanecem no repositório para transição/compatibilidade |
| Documentos gerados | DOCX e PPTX, entregues como download; imagens podem ser geradas pela IA |
| Upload | Upload administrativo em chunks de PDF/DOCX/TXT/Markdown, seguido de reindexação |
| PWA/mobile | Não há manifest, service worker, Capacitor, projeto Android ou projeto iOS |

## Backend, APIs e fluxos

O backend é um monólito FastAPI. Ele concentra autenticação, usuários, assinaturas, webhooks, consulta RAG, geração de documentos, administração e indexação. Isso é compatível com a meta de manter um único backend, mas recomenda-se separar a interface pública em uma API versionada (`/api/v1`) antes do aplicativo móvel.

Grupos de endpoints observados:

- autenticação e conta: cadastro, login, logout, troca de senha;
- assinatura: estado, checkout Asaas e webhooks Asaas/Mercado Pago;
- IA: pergunta normal e streaming, roteiro e slides;
- documentos: listagem de fontes, download de DOCX/PPTX, upload administrativo e reindexação;
- administração: usuários, cupons, acesso gratuito, diagnósticos RAG, base documental;
- operação: health, status e versão.

Não há endpoint de exclusão de conta, rota de exportação de dados ou tela de cancelamento/restauração de compra.

## Variáveis e segredos

As configurações abrangem OpenAI, modelo, diretórios, banco, URL pública, Asaas, Mercado Pago e parâmetros RAG. O arquivo `.env` não foi lido; somente nomes de chaves foram inventariados. Segredos de produção e valores no painel Railway permanecem pendentes de confirmação pelo proprietário.

Nenhuma chave da OpenAI ou de pagamentos deve entrar no bundle Capacitor. Somente identificadores públicos, URL HTTPS da API e chaves públicas estritamente exigidas por SDK podem estar no cliente.

## Responsividade e experiência atual

O CSS possui breakpoints em 760 px e 430 px e algumas tabelas usam overflow horizontal. Isso torna a página utilizável em telas estreitas, mas não constitui experiência móvel completa. Faltam safe areas, navegação própria, estado offline, tratamento do botão voltar, compartilhamento nativo, restauração de sessão móvel, loading global e integração com as lojas.

## Privacidade, conformidade e cabeçalhos

Não foram encontrados política de privacidade completa, termos de uso, URL de suporte ou exclusão de conta. Há apenas textos pontuais sobre o corpus e sobre o tratamento de CPF/CNPJ. Um desses textos afirma envio “direto ao Asaas”, mas o dado passa primeiro pelo backend MagisterIA; o aviso deve ser corrigido e alinhado à política real.

Na resposta pública observada não apareceram CSP, HSTS, `X-Content-Type-Options`, proteção de frame, `Referrer-Policy` ou `Permissions-Policy`. A ausência precisa ser confirmada também no proxy/CDN e corrigida antes da exposição móvel.

## Qualidade e testes

A suíte foi executada em diretório temporário controlado: **55 testes aprovados**, com um aviso de depreciação do Starlette. A primeira tentativa teve erros de infraestrutura por permissão do diretório temporário global; isso não foi tratado como falha do produto.

## Conclusão de prontidão

Classificação: **apto para iniciar adaptação, não apto para submissão às lojas**.

Bloqueadores principais:

1. frontend não empacotável e ausência de API/autenticação móvel contratual;
2. pagamentos digitais ainda não integrados a Play Billing e StoreKit;
3. ausência de política de privacidade, termos, suporte e exclusão de conta;
4. achados de segurança e abuso descritos nos documentos 3 e 7;
5. ausência de projetos nativos, assinatura, assets e testes em dispositivos;
6. falta de decisões do proprietário listadas no documento 11.

