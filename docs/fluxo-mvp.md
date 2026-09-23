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

**Próxima etapa:** extrair afirmações verificáveis dos trechos recuperados e estruturar a comparação com a alegação do usuário.

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
