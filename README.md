# MAGISTERIA

Aplicativo web de pesquisa pastoral em uma base documental fechada. O sistema lê arquivos locais, recupera os trechos mais relevantes e pede à IA que responda **somente** com base nesses trechos, exibindo as fontes utilizadas.

## O que esta versão faz

A versão 0.4.4 reduz o tempo da busca local com metadados preparados em memória, seleção dos melhores candidatos sem ordenar toda a base e análise bíblica por vetores já indexados. A relevância é verificada antes da prioridade editorial, evitando que uma fonte preferencial seja apresentada quando não trata da pergunta.

- aceita arquivos PDF, DOCX, TXT e Markdown;
- mantém um índice vetorial local e persistente;
- atualiza automaticamente a base sempre que o aplicativo é iniciado;
- mostra percentual, documento atual e estimativa de tempo durante a atualização;
- reaproveita o índice dos arquivos inalterados e processa somente documentos novos, modificados ou removidos;
- responde com indicação de arquivo e página/local;
- reconhece pedidos por fontes específicas, combina relevância lexical e vetorial e transmite a resposta progressivamente;
- segue a ordem editorial: Catecismo, Compêndio dos símbolos, Doutrina Social, Suma Teológica, Bíblia Ave Maria e demais documentos;
- mantém o contexto das perguntas recentes e reposiciona o campo abaixo da resposta para continuidade da conversa;
- detecta respostas interrompidas por limite de saída e solicita automaticamente sua continuação;
- consolida o conteúdo em um texto didático único e apresenta as fontes somente depois da resposta;
- exibe parágrafos do Catecismo e dos compêndios, referências bíblicas por livro/capítulo/versículo e referências finais em formato ABNT;
- mantém as respostas anteriores visíveis durante a continuidade da conversa;
- informa quando a base não contém evidência suficiente;
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

Use HTTPS, um proxy reverso e armazenamento persistente para `Documentos` e `banco_vetorial`. Login, upload, pagamentos e os demais módulos futuros não fazem parte desta versão; os serviços estão separados para permitir essa evolução sem reescrever o núcleo.

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
