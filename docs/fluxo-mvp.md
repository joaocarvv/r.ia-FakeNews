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

**Próxima etapa:** conferir a identidade dos artigos por DOI e metadados externos.

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
