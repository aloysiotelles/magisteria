# Changelog

Todas as alterações relevantes deste projeto serão registradas aqui.

## Unreleased

## 0.9.3

- Consultas sobre os quatro Evangelhos passam a ser classificadas como `GOSPEL_QUERY`, inclusive por nome tradicional de episódio, personagem, milagre, parábola e pedido pastoral sem referência explícita.
- A recuperação evangélica começa obrigatoriamente por uma busca exclusiva na Catena Áurea, percorre passagens paralelas, amplia resultados por iteração e carrega chunks adjacentes antes de consultar o restante do acervo.
- A Catena Áurea em português foi integrada ao repositório e recebe metadados estruturados de Evangelho, capítulo, lição, perícope, autoria explícita, obra indicada, documento e adjacência.
- O contexto preserva interpretações distintas e autoria patrística, impede atribuições não rastreáveis e apresenta Scripture, Catena, Magistério e síntese teológica como camadas distintas.
- O cache evangélico agora considera passagens, paralelos, idioma, profundidade, versão da política e versão da coleção Catena, invalidando evidências anteriores à nova política.
- A telemetria registra cumprimento da política Catena, cobertura de paralelos, autores, adjacências, busca complementar, fontes e validações sem armazenar o texto da consulta.
- Preparado o Android `0.9.3 (903)` para atualização na faixa de testes da Play Console.

## 0.9.2

- Incorporadas diretrizes permanentes de linguagem humana, fluida, acolhedora e pastoral, sem reduzir a precisão doutrinária ou a cobertura solicitada.
- Respostas agora adaptam com mais clareza o gênero pedido — catequese, formação ou homilia — e evitam estruturas rígidas semelhantes a relatórios.
- Fontes passam a ser mencionadas com naturalidade, sem repetição excessiva nem referências inventadas.
- Quando não há uma passagem direta, o MAGISTERIA oferece uma síntese prudente dos ensinamentos gerais da Igreja sem expor detalhes técnicos da pesquisa.
- A revisão automática também verifica público, fluidez, legibilidade, completude e ausência de metalinguagem interna.
- Preparado o Android `0.9.2 (902)` para atualização na faixa de testes da Play Console.

## 0.9.1

- Ampliada a taxonomia de listas doutrinais, bíblicas, litúrgicas e históricas, com distinção entre conjuntos fechados e catálogos abertos.
- Removido o recorte dos primeiros itens: listas canônicas inteiras permanecem no plano, na recuperação e na validação da resposta.
- Adicionadas busca por taxonomia e tipos documentais, recuperação de referências cruzadas e prioridade editorial oficial.
- Respostas compostas agora seguem estrutura aprofundada, concluem interrupções técnicas e completam automaticamente itens ausentes.
- Adicionada recuperação de senha com email, token temporário de uso único e revogação das sessões anteriores.
- O aviso pastoral aparece somente na abertura do aplicativo, com apresentação equivalente na Web e no Android.
- Preparado o Android `0.9.1 (901)` para atualização na faixa de testes da Play Console.

## 0.9.0

- Consultas compostas passam por classificação, decomposição temática e plano de cobertura antes da busca.
- Adicionada recuperação documental em camadas, reranking por pertinência e autoridade, deduplicação e orçamento dinâmico de tokens.
- Respostas aprofundadas validam componentes e marcações de fontes antes da entrega.
- Adicionado cache semântico de planos e evidências, invalidado quando o acervo muda; respostas antigas nunca são reutilizadas.
- Adicionado histórico privado por conta, com pesquisa, ordenação, repetição segura, exclusão individual e limpeza integral.
- Adicionadas sugestões relacionadas e adaptação de linguagem por perfil no aplicativo Android.
- Ampliadas as métricas agregadas de custo, tokens, cobertura, cache e latência sem registrar o texto das consultas.
- Preparado o Android `0.9.0 (900)` para a próxima rodada de testes na Play Console.

## 0.8.1

- Corrigida a cor do texto e do cursor no campo de pesquisa do Android.
- Reduzido o tempo de composição dos slides e adicionada conclusão com arte local quando o provedor de imagens demora.
- Ampliado o tempo seguro da geração e melhorado o acompanhamento e o download do arquivo no celular.
- Aproximado o visual móvel da página web e adicionadas ao topo as opções de idioma, administração, base de dados, assinatura, senha, sobre, conta e saída.
- Integrada a assinatura mensal pelo Google Play, com preço localizado, compra, restauração, validação segura no servidor e gerenciamento pela loja.
- Adicionado resgate de cupom na tela de assinatura como alternativa para liberar o acesso completo.

- Criada camada móvel Capacitor 8 para Android e iOS.
- Adicionada autenticação móvel com refresh rotativo e secure storage.
- Preparada abstração unificada de assinatura para web, Google Play e Apple.
- Adicionados fluxos offline, arquivos, compartilhamento, privacidade e exclusão de conta.
- Adicionado CI não assinado para web/API, Android e iOS.
- Corrigidos achados de autenticação, autorização, quotas, diagnósticos e webhook legado.

## 0.8.0

- Versão web poliglota usada como base para a implementação móvel.
