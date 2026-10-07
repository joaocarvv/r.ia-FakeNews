/* Referências obtidas de fontes bibliográficas; nenhuma classificação por LLM. */
(() => {
  let controller;
  const el = (tag, value, cls) => {
    const node = document.createElement(tag);
    if (value !== undefined) node.textContent = String(value);
    if (cls) node.className = cls;
    return node;
  };
  const sourceLink = (record) => {
    const ids = record.identifiers || [];
    const pmid = ids.find(id => /^pmid:\d+$/.test(id));
    const doi = ids.find(id => /^doi:10\.\d{4,9}\/\S+$/.test(id));
    const pmc = ids.find(id => /^pmcid:PMC\d+$/.test(id));
    return pmid ? `https://pubmed.ncbi.nlm.nih.gov/${pmid.slice(5)}/` : pmc ? `https://pmc.ncbi.nlm.nih.gov/articles/${pmc.slice(6)}/` : doi ? `https://doi.org/${encodeURI(doi.slice(4))}` : null;
  };
  const bibliographyLink = url => {
    if (typeof url !== 'string' || !/^https:\/\/(pmc\.ncbi\.nlm\.nih\.gov|pubmed\.ncbi\.nlm\.nih\.gov)\//.test(url)) return null;
    const link = el('a', 'Conferir bibliografia na fonte ↗');
    link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    return link;
  };
  const referenceList = refs => {
    const list = el('ol', undefined, 'reference-list');
    refs.forEach(ref => {
      const item = el('li');
      const label = ref.title || ref.citation || 'Referência sem texto disponível';
      const url = sourceLink(ref);
      if (url) { const link = el('a', label); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; item.append(link); }
      else item.append(el('span', label));
      item.append(el('small', (ref.identifiers || []).join(' · ') || 'Sem identificador para cruzamento automático'));
      (ref.contexts || []).forEach(context => item.append(el('blockquote', context)));
      list.append(item);
    });
    return list;
  };
  function showReport(host, report) {
    host.replaceChildren();
    const nodes = report.nodes || [], names = Object.fromEntries(nodes.map((n, i) => [n.node_id, `A${i+1}`]));
    host.append(el('p', `${report.available_bibliographies} de ${nodes.length} bibliografias disponíveis · ${(report.edges || []).length} ligações identificadas.`, 'reference-coverage'));
    host.append(el('p', 'A seta A1 → A2 significa que A1 inclui A2 na bibliografia. As ligações são confirmadas por PMID, PMCID ou DOI.', 'method-note'));
    const legend = el('ol', undefined, 'reference-articles');
    nodes.forEach(n => legend.append(el('li', `${names[n.node_id]} · ${n.title}${n.role === 'submitted' ? ' (artigo enviado)' : ''}`)));
    host.append(legend, el('h4', 'Quem referencia quem'));
    const edges = report.edges || [];
    if (!edges.length) host.append(el('p', 'Nenhuma ligação identificada nas referências disponíveis. Isso não confirma ausência de citações.', 'article-meta'));
    edges.forEach(edge => {
      const details = el('details', undefined, 'reference-relation');
      details.append(el('summary', `${names[edge.from]} → ${names[edge.to]} · ${edge.has_in_text_context ? 'citação no texto localizada' : 'referência na bibliografia'}`));
      const source = bibliographyLink(edge.source_url); if (source) details.append(source);
      details.append(referenceList(edge.references || []));
      host.append(details);
    });
    host.append(el('h4', 'Referências compartilhadas'));
    const pairs = report.pairs || [];
    if (!pairs.length) host.append(el('p', 'São necessários pelo menos dois artigos para comparar bibliografias.'));
    const comparable = pairs.filter(p => p.comparable);
    const shared = comparable.filter(p => p.shared_count > 0).sort((a,b) => b.shared_count-a.shared_count);
    if (comparable.length && !shared.length) host.append(el('p', 'Nenhuma referência compartilhada identificada entre as bibliografias disponíveis.'));
    shared.forEach(pair => {
      const details = el('details', undefined, 'reference-relation');
      details.append(el('summary', `${names[pair.a]} e ${names[pair.b]} · ${pair.shared_count} referência(s) compartilhada(s)`));
      details.append(el('p', `Sobreposição por identificadores (Jaccard): ${Math.round(pair.jaccard_identified*100)}%. Considera apenas referências com identificadores reconhecidos.`, 'method-note'));
      details.append(referenceList(pair.shared_references || []));
      host.append(details);
    });
    const missing = pairs.length-comparable.length;
    if (missing) host.append(el('p', `${missing} par(es) não puderam ser comparados: uma ou ambas as bibliografias estão indisponíveis.`, 'article-meta'));
    host.append(el('h4', 'Bibliografia de cada artigo'));
    nodes.forEach(n => {
      const details = el('details', undefined, 'reference-relation');
      const available = n.bibliography_status === 'available';
      details.append(el('summary', `${names[n.node_id]} · ${available ? `${n.reference_count} referências` : 'bibliografia indisponível'}`));
      details.append(el('p', available ? `${n.bibliography_source} · ${n.identified_reference_count} obras identificadas; ${n.unidentified_reference_count} referências sem identificador.` : 'O PubMed/PMC não forneceu uma bibliografia consultável nesta consulta. Isso não significa que o artigo não possui referências.', 'method-note'));
      if (available) {
        const source = bibliographyLink(n.bibliography_url); if (source) details.append(source);
        details.append(referenceList(n.references || []));
      }
      host.append(details);
    });
    const limitations = el('details', undefined, 'reference-relation');
    limitations.append(el('summary', 'Como interpretar esta comparação'));
    (report.limitations || []).forEach(value => limitations.append(el('p', value, 'method-note')));
    host.append(limitations);
    if (report.checked_at) host.append(el('p', `Consultado em ${new Date(report.checked_at).toLocaleString('pt-BR')}. O resultado fica salvo nesta análise.`, 'article-meta'));
  }
  window.renderReferenceComparison = (data, options) => {
    if (controller) controller.abort();
    const host = document.getElementById('reference-comparison-content');
    const button = document.getElementById('reference-comparison-check');
    const status = document.getElementById('reference-comparison-status');
    if (!host || !button) return;
    host.replaceChildren(); status.textContent = '';
    let report = data.reference_comparison;
    if (report) showReport(host, report);
    button.textContent = report ? 'Atualizar referências' : 'Verificar referências';
    button.disabled = !options.analysisId || options.busy;
    if (!report) status.textContent = 'Consulte as bibliografias dos artigos desta alegação. Esta verificação não usa LLM.';
    button.onclick = async () => {
      controller = new AbortController(); const current = controller;
      button.disabled = true; status.textContent = 'Consultando referências no PubMed/PMC…';
      try {
        const response = await fetch(`/api/v1/analyses/${encodeURIComponent(options.analysisId)}/references`, {
          method: 'POST', headers: {'Content-Type':'application/json'}, signal: current.signal,
          body: JSON.stringify({claim_id: options.claimId || null, refresh: Boolean(report)})
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error?.message || 'Não foi possível consultar as referências.');
        if (current.signal.aborted) return;
        report = payload; data.reference_comparison = report; showReport(host, report);
        status.textContent = report.status === 'partial' ? 'Consulta concluída com bibliografias indisponíveis. Veja a cobertura abaixo.' : 'Comparação concluída e salva.';
        button.textContent = 'Atualizar referências';
      } catch (error) {
        if (error.name !== 'AbortError') status.textContent = error.message || 'Falha na consulta. Tente novamente.';
      } finally { if (!current.signal.aborted) button.disabled = false; }
    };
  };
})();
