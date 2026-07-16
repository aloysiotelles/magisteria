# Publicação Google Play

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

- Substituir `br.com.seudominio.magisteria` no Capacitor/Gradle.
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
