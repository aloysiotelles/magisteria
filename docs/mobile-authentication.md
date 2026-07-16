# Autenticação móvel

## Modelo

O login web por cookie continua existindo. O aplicativo usa endpoints em `/api/v1/mobile/auth`:

- `POST /login`: autentica a mesma conta e emite tokens;
- `POST /register`: cria o mesmo usuário do web;
- `POST /refresh`: rotaciona o refresh token;
- `POST /logout`: revoga toda a família da sessão;
- `GET /me`: valida o access token;
- `DELETE /api/v1/mobile/account`: exclui após senha e confirmação.

## Tokens

- Access token opaco: 15 minutos.
- Refresh token opaco: 30 dias, rotativo.
- Banco: somente SHA-256 dos tokens, tipo, família, expiração e revogação.
- Reutilização de refresh antigo: revoga toda a família, inclusive tokens emitidos depois.
- Troca de senha: revoga cookies server-side e todas as famílias móveis.

O access token segue `Authorization: Bearer`. Tokens nunca são enviados em URL nem registrados em logs.

## Armazenamento no dispositivo

`@aparajita/capacitor-secure-storage` 8 usa Keychain no iOS e armazenamento protegido pelo Keystore no Android. O bundle não usa `localStorage` para tokens. No navegador de desenvolvimento, a implementação web serve somente para teste local e não representa a garantia do dispositivo.

## 401, expiração e loops

O cliente mantém uma única promessa de refresh para chamadas concorrentes. Cada requisição pode ser repetida no máximo uma vez. Se o refresh falhar, a sessão local é apagada e o usuário retorna ao login. Não há redirecionamento circular.

## Cookies web

- `HttpOnly` e `SameSite=Lax` permanecem.
- Defina `COOKIE_SECURE=true` no Railway.
- O app móvel não depende desses cookies e o CORS móvel não habilita credenciais.

## Testes cobertos

- Login e `/me` com bearer.
- Rotação de refresh.
- Detecção de reutilização e revogação da família.
- Revogação após troca de senha.
- Reautenticação e cascade na exclusão da conta.

## Pendências

- Confirmar política final de duração com o proprietário.
- Definir recuperação de senha/e-mail transacional.
- Considerar proteção por biometria apenas como conveniência local, nunca como substituta do backend.
