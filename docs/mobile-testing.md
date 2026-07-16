# Testes móveis

## Comandos automatizados

```bash
python -m pytest -q
pnpm build
pnpm typecheck
pnpm lint
pnpm test:mobile
pnpm build:web
pnpm audit --audit-level high
pnpm cap:sync
```

Android com JDK 21/SDK 36:

```bash
./android/gradlew -p android bundleDebug lintDebug testDebugUnitTest
```

iOS em `macos-26`/Xcode 26:

```bash
xcodebuild -project ios/App/App.xcodeproj -scheme App \
  -configuration Debug -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
```

## Matriz funcional

| Fluxo | Automatizado | Dispositivo |
| --- | --- | --- |
| Build web/API | Sim | Confirmar deploy de homologação |
| Login/cadastro/logout | API sim | Android e iOS |
| Refresh/expiração/reutilização | API sim | Suspender/retomar app |
| Pergunta/streaming/IA | Rotas existentes | Rede real e lenta |
| Offline/reconexão | Lógica implementada | Modo avião/Wi-Fi |
| 401 sem loop | API/cliente | Sessão expirada |
| Upload em chunks | Backend existente | Arquivos permitidos e grandes |
| DOCX/PPTX | Backend existente | Abrir/Share em apps reais |
| PDF | Browser/visualizador do sistema | PDFs pequenos/grandes |
| Exclusão da conta | API sim | Confirmação e retorno ao login |
| Safe areas/teclado/back | Não | Dispositivos/emuladores |
| Telas pequenas/iPad | CSS | Capturas e inspeção manual |
| Compras | Não configurado | Sandbox após IDs |

## Casos manuais obrigatórios

1. Instalação limpa e atualização sobre versão anterior.
2. Login incorreto, correto e sessão persistida após reinício.
3. Expirar access token e confirmar um único refresh.
4. Alternar rede durante streaming sem repetição infinita.
5. Enviar formulário com duplo toque; somente uma operação.
6. Railway indisponível: banner e botão de nova tentativa.
7. Download/compartilhamento sem permissão ampla.
8. Upload interrompido, arquivo vazio, extensão inválida e chunk acima do limite.
9. Voltar Android com diálogo aberto, histórico e tela inicial.
10. VoiceOver/TalkBack, tamanho de fonte, contraste e foco.
11. Exclusão com senha errada/correta e assinatura ativa.
12. Links externos abrem Browser; host não permitido é bloqueado.

## Ambientes não disponíveis nesta execução

- Android Studio, JDK e Android SDK locais: build Gradle não executado neste Windows.
- Mac/Xcode 26: build iOS, simulador, assinatura e Archive não executados.
- Contas Play/App Store: Billing, StoreKit, TestFlight e Console não executados.

O workflow `.github/workflows/mobile-ci.yml` prepara validação Android e iOS sem certificados. Builds assinados permanecem desativados.

## Resultado desta implementação

- Backend: 65 testes aprovados.
- Cliente móvel: 2 testes Vitest aprovados; TypeScript, ESLint e build Vite aprovados.
- Dependências JavaScript: instalação reproduzível e auditoria sem vulnerabilidades conhecidas.
- Capacitor: sincronização Android/iOS aprovada e manifesto Swift Package Manager normalizado.
- Builds nativos locais: não executados pelas limitações de ambiente descritas acima; permanecem cobertos pelo workflow de CI.
