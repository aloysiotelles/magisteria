# Variáveis de ambiente móvel

## Públicas e compiladas

| Variável | Local | Produção | Sensível |
| --- | --- | --- | --- |
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | Railway HTTPS | Não |
| `VITE_ENVIRONMENT` | `development` | `production` | Não |
| `CAPACITOR_APP_ID` | placeholder permitido | ID definitivo | Não |

Somente variáveis `VITE_*` entram no JavaScript. Nunca usar esse prefixo para credenciais.

## Backend/Railway

| Variável | Finalidade | Sensível |
| --- | --- | --- |
| `ADMIN_BOOTSTRAP_PASSWORD` | Primeiro bootstrap; remover depois | Sim |
| `COOKIE_SECURE` | Cookie HTTPS | Não |
| `MOBILE_ALLOWED_ORIGINS` | CORS Capacitor | Não |
| `RATE_LIMIT_ENABLED` | Limites por rota | Não |
| `MAX_UPLOAD_CHUNK_BYTES` | Limite de parte | Não |
| `APP_PUBLIC_URL` | URL pública | Não |
| `APP_DATABASE_FILE` | SQLite | Não |
| `OPENAI_API_KEY` | OpenAI | Sim |
| `ASAAS_API_KEY` | API Asaas | Sim |
| `ASAAS_WEBHOOK_TOKEN` | Autenticação webhook | Sim |
| `MERCADO_PAGO_ACCESS_TOKEN` | Legado | Sim |
| `MERCADO_PAGO_WEBHOOK_SECRET` | HMAC legado | Sim |
| `RAG_DIAGNOSTIC_RETENTION_DAYS` | TTL | Não |
| `GOOGLE_PLAY_PRODUCT_ID` | Produto Android | Não |
| `APPLE_PRODUCT_ID` | Produto Apple | Não |
| `APPLE_SHARED_SECRET` | Validação Apple futura | Sim |
| `GOOGLE_SERVICE_ACCOUNT_CREDENTIALS` | Validação Google futura | Sim |

## Recomendações

- Railway: configure valores no painel, não em `.env` versionado.
- GitHub: certificados, keystores e credenciais somente em Environments protegidos com reviewers.
- Credencial Google deve preferir JSON base64/Workload Identity e ser materializada apenas durante o job.
- Certificados Apple devem ser temporários no keychain do runner e apagados ao final.
- Nunca registrar o conteúdo das variáveis; listar somente nomes.

## Validação

`mobile/scripts/validate-env.mjs` bloqueia build de produção com URL ausente, local ou HTTP. O CSP do `mobile/index.html` também deve ser atualizado caso o domínio Railway definitivo mude.

## Troca de ambiente

Para homologação, não edite URLs no TypeScript. Passe `VITE_API_BASE_URL=https://homologacao.example` ao build e acrescente esse host ao CSP/allowlist de forma revisada.
