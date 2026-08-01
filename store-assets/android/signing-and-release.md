# Assinatura e geração do AAB Android

## Modelo adotado

O MAGISTERIA usa duas chaves distintas:

1. **Upload key**, mantida pelo publicador, assina o AAB enviado ao Google Play e comprova que a atualização foi autorizada.
2. **App signing key**, mantida pelo Google Play App Signing, assina os APKs finais entregues aos usuários.

A upload key não é uma chave de API nem uma credencial de pagamento. O arquivo `.jks` e suas senhas nunca devem entrar no Git, em tickets, e-mails ou mensagens. Uma cópia de recuperação deve ficar em local seguro e separado da conta principal da Play Console.

## Automação preparada

O workflow manual `.github/workflows/android-release.yml` usa o ambiente protegido `google-play` e espera quatro secrets:

- `ANDROID_KEYSTORE_BASE64`
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`

O keystore é reconstruído apenas na área temporária do executor, o AAB é assinado e o arquivo temporário é destruído com o executor. O artefato fica disponível por 14 dias no GitHub Actions.

## Sequência operacional

1. Explicar este modelo ao proprietário e obter autorização expressa para gerar a upload key.
2. Gerar uma chave RSA com pelo menos 2048 bits, fora do repositório.
3. Entregar ao proprietário o local do backup e instruções de recuperação, sem mostrar as senhas em logs.
4. Criar o ambiente `google-play` no GitHub e cadastrar os quatro secrets.
5. Executar manualmente o workflow `Android signed release`.
6. Verificar assinatura, package name `br.com.aloysiotelles.magisteria`, `versionCode 903`, `versionName 0.9.3` e `targetSdk 36`.
7. Enviar o AAB ao teste fechado e deixar o Google gerar/proteger a app signing key.

Cada atualização futura deve usar a mesma upload key e um `versionCode` maior.
