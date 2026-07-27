# Publicação Google Play

## Registro criado no Play Console

- Criado em 27/07/2026 na conta pessoal de Aloysio Telles de Moraes Netto.
- Nome: `MAGISTERIA`.
- Application ID: `br.com.aloysiotelles.magisteria`.
- ID interno do Play Console: `4975624098480909728`.
- Idioma padrão: português do Brasil.
- Tipo e preço inicial: aplicativo gratuito.
- Produção bloqueada até concluir a configuração, publicar um teste fechado e manter pelo menos 12 participantes por 14 dias.
- Estado em 27/07/2026: 5 de 11 tarefas de conteúdo concluídas. Foram salvas a política de privacidade e as declarações de anúncios, app governamental, recursos financeiros e saúde. Categoria `Educação`, e-mail e site de suporte também foram cadastrados.

## Decisões e bloqueios registrados em 27/07/2026

- O proprietário declarou que o aplicativo não é infantil. Antes de enviar o formulário de público-alvo, confirmar se a seleção será exclusivamente 18 anos ou mais; essa é a recomendação técnica atual.
- Antes do primeiro AAB assinado, explicar ao proprietário a função da upload key, gerar a chave fora do Git e criar uma cópia de recuperação segura. Não gerar nem enviar a chave sem essa explicação.
- A implementação móvel e a preparação de publicação foram integradas à `main` pelos PRs [#1](https://github.com/aloysiotelles/magisteria/pull/1) e [#2](https://github.com/aloysiotelles/magisteria/pull/2), com CI verde.
- O Railway publicou a versão `0.8.0`. `/health`, `/privacy`, `/terms`, `/support`, `/account-deletion` e `/app-version` foram validados publicamente em 27/07/2026.
- Ícone 512 × 512, feature graphic 1024 × 500 e textos pt-BR estão em `store-assets/android/`.
- O workflow manual protegido `Android signed release` está preparado. A upload key ainda não foi gerada e nenhum segredo foi adicionado ao GitHub.

## Requisitos técnicos atuais

- Aplicativo Android Capacitor 8, `minSdk 24`, `compileSdk 36`, `targetSdk 36`.
- A partir de 31/08/2026, novos apps e atualizações devem mirar Android 16/API 36. Consulte [Target API](https://developer.android.com/google/play/requirements/target-sdk).
- O projeto usa somente `android.permission.INTERNET`.
- HTTP claro, backup de aplicativo e backup completo estão desabilitados.
- Builds API 35+ devem suportar páginas de 16 KB; plugins Capacitor usados não adicionam biblioteca nativa própria fora das dependências compatíveis. Validar o AAB no Play Console.

## Build local

Pré-requisitos: Node 22+, pnpm 11.9, JDK 21, Android Studio atual e SDK/Build Tools 36.

```bash
pnpm install --frozen-lockfile
pnpm build:web
pnpm cap:sync:android
pnpm cap:android
```

No Android Studio: aguarde o Gradle Sync e execute em emulador/dispositivo. Para bundle:

```bash
cd android
./gradlew bundleRelease
```

O AAB assinado será produzido em `android/app/build/outputs/bundle/release/`. Não há keystore no repositório.

## Antes de assinar

- Identificador definitivo confirmado no Capacitor/Gradle: `br.com.aloysiotelles.magisteria`.
- Publicador: Aloysio Telles de Moraes Netto (conta pessoal).
- E-mail público de suporte: `aplicativo.magisteria@gmail.com`.
- URLs públicas validadas: `https://magisteria-production.up.railway.app/privacy`, `/terms`, `/support` e `/account-deletion`.
- Confirmar `versionName=0.8.0` e incrementar `versionCode` acima de 800 a cada upload.
- Criar upload key offline e ativar Play App Signing.
- Configurar secrets somente no GitHub Environment protegido se build assinado for automatizado.

## Play Console

- Conta e identidade do desenvolvedor verificadas.
- Nome, descrição curta/completa e categoria.
- Ícone 512, feature graphic e screenshots de telefone/tablet.
- URL HTTPS de privacidade, suporte e exclusão.
- Data Safety coerente com conta, consultas, pagamentos, diagnósticos e terceiros.
- Questionário de conteúdo, público-alvo, anúncios e acesso ao app.
- Instruções/conta de revisão sem privilégio administrativo.
- Produtos Play Billing antes de habilitar compras móveis.

Contas pessoais criadas após 13/11/2023 normalmente precisam de teste fechado com pelo menos 12 participantes por 14 dias contínuos antes do acesso à produção: [requisito de teste](https://support.google.com/googleplay/android-developer/answer/14151465?hl=en).

## Trilhas sugeridas

1. Internal testing para QA técnico.
2. Closed testing com grupo exigido.
3. Open testing opcional.
4. Production com rollout 5% → 20% → 50% → 100%, observando crashes, ANRs, login e API.

## Checklist de revisão

- Login, logout, refresh e exclusão funcionam.
- Offline e falha Railway mostram mensagem, nunca tela branca.
- Voltar Android fecha diálogo/volta/minimiza corretamente.
- Upload e arquivos não pedem permissão ampla de armazenamento.
- Checkout web de bens digitais não aparece no app.
- Política/termos/suporte não contêm texto provisório na submissão final.

## Rollback

Pausar rollout, desabilitar funcionalidade por flag server-side se disponível e publicar build corrigido com `versionCode` maior. Nunca apagar a API usada pela versão já instalada.
