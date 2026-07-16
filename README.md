# MAGISTERIA

Aplicativo web de pesquisa pastoral em uma base documental fechada. O sistema lê arquivos locais, recupera os trechos mais relevantes e pede à IA que responda **somente** com base nesses trechos, exibindo as fontes utilizadas.

## O que esta versão faz

A versão 0.6.6 combina busca textual e orientação pelos índices internos das obras. Quando o usuário digita uma palavra isolada, a consulta nominal segue o sumário do Catecismo, o índice do Compêndio de Símbolos e o sumário de A Fé Explicada; as remissões e os contextos encontrados também orientam a varredura de toda a documentação antes de um retorno negativo.

- aceita arquivos PDF, DOCX, TXT e Markdown;
- mantém um índice vetorial local e persistente;
- atualiza automaticamente a base sempre que o aplicativo é iniciado;
- mostra percentual, documento atual e estimativa de tempo durante a atualização;
- reaproveita o índice dos arquivos inalterados e processa somente documentos novos, modificados ou removidos;
- responde com indicação de arquivo e página/local;
- reconhece pedidos por fontes específicas, combina relevância lexical e vetorial e transmite a resposta progressivamente;
- segue a ordem editorial: Catecismo, Compêndio dos símbolos, Doutrina Social, Suma Teológica, Bíblia Ave Maria e demais documentos;
- mantém o contexto das perguntas recentes e posiciona o prompt de continuação dentro da resposta atual, logo abaixo dos botões de roteiro e slides;
- detecta respostas interrompidas por limite de saída e solicita automaticamente sua continuação;
- consolida o conteúdo em um texto didático único e apresenta as fontes somente depois da resposta;
- aplica às respostas, roteiros e slides um padrão editorial sintetizado da análise integral das homilias de São João Paulo II cadastradas;
- exibe parágrafos do Catecismo e dos compêndios, referências bíblicas por livro/capítulo/versículo e referências finais em formato ABNT;
- mantém as respostas anteriores visíveis durante a continuidade da conversa;
- informa quando a base não contém evidência suficiente;
- permite ao Admin criar cupons promocionais com validade de um dia, uma semana ou um mês e revogar individualmente acessos concedidos por cupom;
- não realiza pesquisa na internet nem usa ferramentas de busca aberta;
- oferece as rotas `GET /`, `POST /perguntar`, `POST /indexar` e `GET /status`.

> A API de IA é acessada apenas para redigir a resposta a partir dos trechos locais enviados no contexto. O aplicativo não habilita busca web, ferramentas externas ou conhecimento documental fora da pasta `Documentos`.

## Início simples no Windows

1. Dê dois cliques em `iniciar_magisteria.bat`.
2. Na primeira execução, o aplicativo prepara o ambiente e abre o arquivo `.env`.
3. Substitua `sua_chave_aqui` pela chave da API, salve e feche o arquivo.
4. Execute novamente `iniciar_magisteria.bat`.
5. Aguarde a atualização automática da base. O navegador abrirá em `http://127.0.0.1:8000` somente quando o aplicativo estiver pronto.
Se uma versão anterior ainda estiver aberta, o inicializador detectará a diferença e usará automaticamente outra porta local para abrir a versão atualizada.

O usuário final não precisa digitar comandos no terminal.

## Como cadastrar documentos

1. Copie arquivos `.pdf`, `.docx`, `.txt`, `.md` ou `.markdown` para a pasta `Documentos`.
2. Inicie ou reinicie o MAGISTERIA.
3. Verifique no topo do formulário quantos documentos e trechos foram indexados.

Se existir um arquivo `.md` com o mesmo nome-base de um PDF, o Markdown tem prioridade e o PDF é ignorado na indexação. Isso permite manter a versão leve da base sem perder compatibilidade com a pasta antiga.

Arquivos corrompidos ou sem texto legível são ignorados e apresentados no retorno de status. PDFs compostos somente por imagens precisam passar por OCR antes de serem cadastrados.

## Instalação manual para desenvolvimento

Requer Python 3.11 ou mais recente.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app:app --reload
```

## Configuração

O arquivo `.env` aceita:

- `OPENAI_API_KEY`: chave obrigatória para gerar respostas;
- `OPENAI_MODEL`: modelo usado na redação da resposta;
- `OPENAI_REVIEW_MODEL`: modelo usado para conferir e aprovar a resposta final;
- `APP_PUBLIC_URL`: endereço HTTPS público da aplicação (no Railway, o domínio também é detectado automaticamente);
- `ASAAS_API_KEY`: chave da API do ambiente correto;
- `ASAAS_WEBHOOK_TOKEN`: segredo exclusivo do webhook, com pelo menos 32 caracteres e diferente da chave da API;
- `ASAAS_API_BASE_URL`: `https://api-sandbox.asaas.com/v3` para homologação ou `https://api.asaas.com/v3` para produção;
- `ASAAS_PRICE`: valor mensal da assinatura, com ponto decimal (por exemplo, `14.99`);
- `ASAAS_BILLING_TYPE`: forma de cobrança; `UNDEFINED` permite que o assinante escolha no link do Asaas;
- `ASAAS_CALLBACK_ENABLED`: habilita o retorno automático ao aplicativo; use `false` apenas no Sandbox quando o domínio de homologação não estiver cadastrado no Asaas;
- `FREE_ACCESS_COUPONS`: cupons de cortesia separados por vírgula; vazio desativa o resgate;
- `MAX_CONTEXT_CHUNKS`: máximo de trechos enviados por pergunta;
- `MIN_RELEVANCE_SCORE`: limiar mínimo para aceitar um trecho;
- `CHUNK_SIZE` e `CHUNK_OVERLAP`: tamanho e sobreposição dos trechos.

Nunca publique o arquivo `.env`. Ele já está protegido pelo `.gitignore`.

## Estrutura

```text
magister-ia/
├── Documentos/          # fonte documental fechada
├── banco_vetorial/      # índice local gerado automaticamente
├── services/            # leitura, recuperação e geração de respostas
├── static/              # logo, estilos e comportamento da interface
├── templates/           # páginas HTML
├── tests/               # testes automatizados
├── app.py               # aplicação e rotas FastAPI
├── config.py            # configuração central
└── requirements.txt
```

## Preparação para hospedagem

Em produção, defina as variáveis de ambiente no servidor e execute:

```powershell
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

Use HTTPS, um proxy reverso e armazenamento persistente para `Documentos` e `banco_vetorial`.

### Ativação do Asaas

1. Gere a chave em **Integrações > Chaves de API** no ambiente correto e guarde-a diretamente nas variáveis do servidor.
2. Preencha `APP_PUBLIC_URL` e as cinco variáveis `ASAAS_*` descritas acima. Sandbox e produção têm chaves independentes.
3. Em **Integrações > Webhooks**, cadastre `https://SEU-DOMINIO/webhooks/asaas`, defina um token exclusivo de 32 a 255 caracteres e habilite os eventos de pagamento.
4. Homologue uma assinatura no Sandbox e confira a sequência `PAYMENT_CREATED` e `PAYMENT_CONFIRMED`/`PAYMENT_RECEIVED`.
5. Antes da abertura ao público, troque a URL e a chave pelas credenciais de produção e repita uma compra real de baixo valor.

O checkout cria uma assinatura mensal de R$ 14,99 e abre a cobrança hospedada pelo Asaas. A aplicação só libera o acesso depois de consultar novamente cobrança e assinatura na API e conferir referência, valor, moeda e vínculo. O corpo do webhook e os parâmetros de retorno não são aceitos como prova de pagamento. Eventos repetidos são processados de forma idempotente.
O CPF/CNPJ exigido pelo Asaas é validado no servidor e enviado ao provedor no momento do checkout, sem ser armazenado no banco do MAGISTERIA.

## Atalhos de deploy

Dentro da pasta `magister-ia`, estes atalhos ficam disponíveis no terminal:

```powershell
SUBA
SUBA ISTO C:\caminho\do\arquivo.pdf
```

- `SUBA` publica a aplicação usando o fluxo de deploy já existente.
- `SUBA ISTO` copia um arquivo permitido para `Documentos`, envia a base remota e reindexa ao final.

O atalho `SUBA ISTO` aceita apenas `.md`, `.txt`, `.docx` e `.pdf`. Se você anexar o arquivo no prompt e chamar `SUBA ISTO`, ele tenta localizar automaticamente o anexo mais recente compatível; se quiser, também pode informar o caminho manualmente.

## Deploy no Railway

O deploy de producao usa o `Dockerfile`. O processo escuta automaticamente a porta fornecida pelo Railway e o endpoint `GET /health` e usado como health check.

### 1. Criar e configurar o servico

Ao conectar este repositorio pelo painel do Railway, defina **Root Directory** como `/magister-ia`. Depois, cadastre estas variaveis em **Variables**:

```dotenv
OPENAI_API_KEY=coloque_a_chave_no_painel
OPENAI_MODEL=gpt-5.4-nano
OPENAI_IMAGE_MODEL=gpt-image-1
IMAGE_CONCURRENCY=3
IMAGE_QUALITY=low
DOCUMENTS_DIR=/data/Documentos
VECTOR_DIR=/data/banco_vetorial
MAX_CONTEXT_CHUNKS=16
MIN_RELEVANCE_SCORE=0.08
CHUNK_SIZE=1100
CHUNK_OVERLAP=180
```

Nao defina `PORT`: o Railway injeta essa variavel automaticamente. Nunca envie o arquivo `.env` ao repositorio.

### 2. Persistir a base documental

Adicione um Volume ao servico e use `/data` como caminho de montagem. Os documentos devem ficar em `/data/Documentos`; o indice sera criado em `/data/banco_vetorial` quando o container iniciar.

Os PDFs nao fazem parte da imagem Docker nem do repositorio. Isso evita publicar material privado ou protegido e mantem a imagem pequena. Antes de liberar o servico, copie os arquivos autorizados para o diretorio `Documentos` do Volume e reinicie o deploy. Para esta nova base, prefira enviar os arquivos `.md` gerados a partir dos PDFs, porque eles reduzem bastante o peso do volume e mantêm a indexacao local funcionando do mesmo jeito. Confirme o carregamento em `GET /status`.

Para substituir toda a base remota por arquivos de texto/Markdown da pasta local `Documentos`, use:

```powershell
python upload_documents.py --substituir
```

Esse comando apaga os documentos antigos do Volume do Railway, envia apenas `.md`, `.markdown` e `.txt`, e reindexa a base ao final.

> Um servico com Volume deve usar uma unica replica, porque o indice JSON e um arquivo local compartilhado pela aplicacao.

### 3. Publicar

Pelo GitHub, dispare o deploy no painel depois de configurar a raiz, as variaveis e o Volume. Pela CLI do Railway:

```powershell
railway login
railway init
railway up .\magister-ia --path-as-root
railway logs
```

Para um projeto ja vinculado, novos deploys usam `railway up .\magister-ia --path-as-root`.

### Verificacao local antes do deploy

```powershell
python -m pip install -r requirements.txt
python -m pytest
python -m compileall -q app.py config.py services tests
docker build -t magister-ia .
docker run --rm -p 8000:8000 --env-file .env magister-ia
```

Abra `http://localhost:8000/health` e espere `{"status":"ok", ...}`. O endpoint `/status` informa o andamento da indexacao e eventuais erros de leitura.

## Regra absoluta de resposta

> Responda somente com base nos trechos fornecidos. Se os trechos não forem suficientes, diga que não encontrou essa informação nos documentos cadastrados.
