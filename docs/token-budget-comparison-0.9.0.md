# Comparação de orçamento de tokens — MAGISTERIA 0.9.0

## Comparação estrutural antes da publicação

| Cenário | Estratégia anterior | Estratégia 0.9.0 | Efeito esperado |
|---|---:|---:|---|
| Consulta simples | mínimo de 16 trechos; saída até 2.400 tokens | até 6 trechos; contexto até 6.200 tokens; saída até 2.000 | 62,5% menos trechos candidatos e 16,7% menos saída máxima |
| Resumo dos sete sacramentos | 16 trechos gerais; saída até 2.400 | até 5 trechos gerais + 1 por sacramento, deduplicados; contexto até 4.200; saída até 1.200 | até 25% menos trechos brutos e 50% menos saída máxima, preservando os sete itens |
| Estudo aprofundado dos sete sacramentos | 16 trechos gerais; saída até 2.400 | busca geral + até 3 trechos por componente; deduplicação; contexto final até 10.500; saída até 5.000 | orçamento maior somente para a classe aprofundada, com cobertura por componente |

Os percentuais de trechos comparam os limites de recuperação, não uma promessa de redução idêntica na fatura. O tamanho de cada trecho varia. A classificação, a decomposição, a taxonomia, a deduplicação e as sugestões são determinísticas e não consomem uma chamada adicional ao modelo.

## Medição em operação

Cada consulta registra apenas métricas técnicas e agregáveis: versão da estratégia, profundidade, categoria, quantidade de componentes e trechos, tokens estimados de entrada e saída, contexto, custo estimado, latência, cache, falhas de cobertura, erros de citação, regenerações e erros de geração. O endpoint administrativo de métricas agrupa esses dados por `strategy_version`, permitindo comparar `legacy` com `layered-rag-1` sem armazenar o texto da pergunta.

Registros antigos podem conter somente `context_tokens`; por isso a comparação identifica quantas consultas têm medição completa do modelo e não trata zeros legados como consumo real. A conclusão financeira deverá ser tomada após volume suficiente na faixa de testes, separando consultas simples, resumidas e aprofundadas.

## Teste real controlado

Em 29/07/2026, usando a chave já autorizada e trechos locais do acervo, uma consulta simples e uma consulta composta concluíram o fluxo principal + revisão. A consulta simples terminou com cobertura aprovada, cinco fontes efetivamente marcadas e 3.665 caracteres; a consulta dos sete sacramentos terminou com cobertura aprovada, nove fontes marcadas, nenhum componente ausente ou superficial e 7.083 caracteres. Nenhuma resposta nem chave foi persistida no relatório.
