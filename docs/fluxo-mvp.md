# Fluxo principal do MVP

## Objetivo

Permitir que o usuário verifique uma alegação sobre saúde com base em evidências científicas.

## Entrada

- Alegação sobre saúde em texto, obrigatória.
- Link ou DOI de um artigo científico, opcional.

**Etapa concluída:** validação da entrada.

**Comprovação:** [`notebooks/01_validacao_entrada.ipynb`](../notebooks/01_validacao_entrada.ipynb).

**Etapa concluída:** preparação da alegação para busca científica.

**Comprovação:** [`notebooks/02_validacao_plano_busca.ipynb`](../notebooks/02_validacao_plano_busca.ipynb).

**Etapa concluída:** consultar o PubMed e normalizar os artigos encontrados.

**Comprovação:** [`notebooks/03_validacao_pubmed.ipynb`](../notebooks/03_validacao_pubmed.ipynb).

**Etapa concluída:** conferir a identidade dos artigos por DOI e metadados externos.

**Comprovação:** [`notebooks/04_validacao_identidade_crossref.ipynb`](../notebooks/04_validacao_identidade_crossref.ipynb).

**Etapa concluída:** obter resumo e texto completo disponível no PubMed Central.

**Comprovação:** [`notebooks/05_validacao_conteudo_pmc.ipynb`](../notebooks/05_validacao_conteudo_pmc.ipynb).

**Etapa concluída:** dividir o conteúdo em trechos rastreáveis para recuperação de evidências.

**Comprovação:** [`notebooks/06_validacao_chunking.ipynb`](../notebooks/06_validacao_chunking.ipynb).

**Etapa concluída:** recuperar e ordenar lexicalmente os trechos mais relevantes para a alegação.

**Comprovação:** [`notebooks/07_validacao_recuperacao_lexical.ipynb`](../notebooks/07_validacao_recuperacao_lexical.ipynb).

**Etapa concluída:** recuperar semanticamente trechos em inglês a partir de uma alegação em português e comparar a seleção com a linha de base lexical.

**Comprovação:** [`notebooks/08_validacao_recuperacao_semantica.ipynb`](../notebooks/08_validacao_recuperacao_semantica.ipynb).

**Etapa concluída:** combinar BM25 e embeddings em um ranking híbrido por posições, sem somar scores incompatíveis.

**Comprovação:** [`notebooks/09_validacao_ranking_hibrido.ipynb`](../notebooks/09_validacao_ranking_hibrido.ipynb).

**Etapa concluída:** extrair afirmações científicas rastreáveis e estruturar pares de comparação ainda não classificados.

**Comprovação:** [`notebooks/10_validacao_extracao_evidencias.ipynb`](../notebooks/10_validacao_extracao_evidencias.ipynb).

**Etapa concluída:** classificar cada par como apoio, contradição, evidência neutra ou incerta, preservando probabilidades, modelo, justificativa e proveniência.

**Comprovação:** [`notebooks/11_validacao_classificacao_relacoes.ipynb`](../notebooks/11_validacao_classificacao_relacoes.ipynb).

**Etapa concluída:** agregar primeiro por artigo e depois entre artigos, ponderando perfis explícitos de qualidade e preservando conflitos e insuficiência de evidência.

**Comprovação:** [`notebooks/12_validacao_sintese_evidencias.ipynb`](../notebooks/12_validacao_sintese_evidencias.ipynb).

**Etapa concluída:** enriquecer os perfis de qualidade com validações externas de identidade, retratação, protocolo aplicável, desenho declarado e disponibilidade de dados.

**Comprovação:** [`notebooks/13_validacao_qualidade_artigo.ipynb`](../notebooks/13_validacao_qualidade_artigo.ipynb).

**Etapa concluída:** aplicar o AMSTAR 2 à revisão sistemática, registrando evidência por item e derivando a confiança por falhas críticas, sem escore numérico.

**Comprovação:** [`notebooks/14_validacao_amstar2.ipynb`](../notebooks/14_validacao_amstar2.ipynb).

**Etapa concluída:** incorporar o perfil metodológico avaliado à síntese e gerar uma resposta explicável ao usuário, separando sinal, força da evidência, confiança metodológica, limitações e fontes.

**Comprovação:** [`notebooks/15_validacao_resposta_explicavel.ipynb`](../notebooks/15_validacao_resposta_explicavel.ipynb).

**Etapa concluída:** encapsular o fluxo em um serviço de aplicação que busque e processe múltiplos artigos independentes, tolere falhas isoladas e devolva o relatório estruturado.

**Comprovação:** [`notebooks/17_validacao_orquestracao_multiartigo.ipynb`](../notebooks/17_validacao_orquestracao_multiartigo.ipynb).

**Etapa concluída:** expor o serviço por uma API HTTP assíncrona, com contrato de entrada, consulta de progresso, resultado estruturado e erros seguros.

**Comprovação:** [`notebooks/18_validacao_api_http.ipynb`](../notebooks/18_validacao_api_http.ipynb).

**Etapa concluída:** impedir que evidências inteiramente incertas sustentem uma conclusão e excluir artigos com retratação confirmada da síntese, mantendo ambos os casos auditáveis.

**Comprovação:** [`notebooks/19_validacao_confiabilidade.ipynb`](../notebooks/19_validacao_confiabilidade.ipynb).

**Etapa concluída:** revisar a interpretação das evidências por dois papéis independentes — pesquisador e crítico — e submeter suas saídas a um árbitro determinístico que valida citações, impede a promoção de evidência insuficiente e explicita a necessidade de abstenção.

**Comprovação:** [`notebooks/20_validacao_pesquisa_adversarial.ipynb`](../notebooks/20_validacao_pesquisa_adversarial.ipynb).

Essa etapa valida regras de software com agentes controlados; não representa validação clínica nem demonstra que uma IA possa validar outra IA.

**Etapa concluída:** auditar todas as fontes sugeridas pelo grupo, separando descoberta, conteúdo, validação, plataformas editoriais e conferência manual. O teste ao vivo confirmou acesso a PubMed, PMC, ClinicalTrials.gov, Crossref/Retraction Watch, OpenAlex, DataCite, catálogo SciELO, Springer Nature Meta, Springer Nature Open Access e ScienceDirect.

**Comprovação:** [`notebooks/21_validacao_fontes_cientificas.ipynb`](../notebooks/21_validacao_fontes_cientificas.ipynb).

Nature não é contada como índice independente, e Google Acadêmico permanece fora da automação por não possuir uma API pública suportada no projeto. A disponibilidade de uma fonte não comprova cobertura, relevância nem qualidade científica.

**Próxima etapa:** implementar a busca federada em PubMed, OpenAlex e SciELO, normalizando e deduplicando os resultados por DOI, PMID e metadados antes do ranking. Depois, integrar adaptadores reais e versionados para os agentes e construir o conjunto prata.

## Fluxo

1. O usuário envia a alegação e, opcionalmente, um artigo.
2. O sistema identifica e normaliza a alegação.
3. O sistema busca artigos científicos relacionados.
4. O sistema seleciona e analisa as evidências encontradas.
5. O sistema compara as evidências com a alegação.
6. O sistema gera um relatório para o usuário.

## Saída

O relatório deve apresentar:

- conclusão sobre a compatibilidade da alegação com as evidências;
- justificativa em linguagem clara;
- limitações da análise;
- links para as fontes utilizadas.

## Resumo visual

```text
Alegação + artigo opcional
            ↓
  Busca de evidências
            ↓
 Análise e comparação
            ↓
Relatório + justificativa + fontes
```
