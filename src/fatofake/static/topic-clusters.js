(() => {
  let activeController = null;
  const colors = ['#3659d9', '#21866d', '#a75d31', '#8055b8', '#c04265', '#1b8798', '#8b7928'];
  const color = id => id < 0 ? '#9aa3af' : colors[id % colors.length];
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  window.cancelPubmedClusters = () => {
    activeController?.abort();
    activeController = null;
  };
  window.showPubmedClusters = async (articles, results) => {
    window.cancelPubmedClusters();
    const controller = new AbortController();
    activeController = controller;
    const panel = element('section', undefined, 'topic-clusters');
    panel.setAttribute('aria-label', 'Grupos de temas dos artigos');
    panel.append(element('h3', 'Explore os artigos por tema'));
    const status = element('p', 'Identificando grupos com BERTopic…', 'hint');
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    panel.append(status);
    results.prepend(panel);
    const titles = new Map(articles.map(article => [article.pmid, article.title_pt || article.title]));
    const cards = Array.from(results.querySelectorAll('.topic-card'));
    try {
      const response = await fetch('/api/v1/pubmed-clusters', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, signal: controller.signal,
        body: JSON.stringify({articles: articles.map(({pmid, title}) => ({pmid, title}))})
      });
      const data = await response.json();
      if (controller.signal.aborted || !panel.isConnected) return;
      if (!response.ok) throw new Error(data.error?.message || 'Grupos de temas indisponíveis.');
      if (data.status !== 'available') {
        status.textContent = data.message || 'Não há artigos suficientes para agrupar os temas.';
        return;
      }
      status.textContent = `${data.topic_count} grupo(s) de temas em ${data.document_count} artigos desta página. ${data.limitation}`;
      if (data.topic_count === 0) status.textContent = `Não foram encontrados grupos consistentes nesta página. ${data.limitation}`;
      const controls = element('div', undefined, 'topic-cluster-controls');
      const selection = element('p', `Exibindo todos os ${articles.length} artigos.`, 'topic-cluster-selection');
      selection.setAttribute('role', 'status');
      const buttons = [];
      let dots = [];
      const filter = (cluster) => {
        const members = cluster ? new Set(cluster.pmids) : null;
        cards.forEach(card => { card.hidden = !!members && !members.has(card.dataset.pmid); });
        buttons.forEach(({button, topicId}) => button.setAttribute('aria-pressed', String(topicId === (cluster?.topic_id ?? null))));
        dots.forEach(({dot, point}) => dot.setAttribute('opacity', !members || members.has(point.pmid) ? '1' : '.18'));
        selection.textContent = cluster ? `${cluster.count} artigo(s) no grupo: ${cluster.label}.` : `Exibindo todos os ${articles.length} artigos.`;
      };
      const all = element('button', `Todos · ${articles.length}`, 'secondary topic-cluster-button');
      all.type = 'button'; all.setAttribute('aria-pressed', 'true');
      all.addEventListener('click', () => filter(null));
      buttons.push({button: all, topicId: null}); controls.append(all);
      data.clusters.forEach(cluster => {
        const button = element('button', undefined, 'secondary topic-cluster-button');
        button.type = 'button'; button.setAttribute('aria-pressed', 'false');
        button.style.setProperty('--cluster-color', color(cluster.topic_id));
        button.append(element('strong', cluster.is_outlier ? 'Sem grupo definido' : `Tema ${cluster.topic_id + 1} · ${cluster.count} artigo(s)`));
        if (cluster.is_outlier) button.append(element('span', `${cluster.count} artigo(s)`));
        else button.append(element('span', cluster.label));
        button.title = (cluster.terms || []).join(', ');
        button.addEventListener('click', () => filter(cluster));
        buttons.push({button, topicId: cluster.topic_id}); controls.append(button);
      });
      panel.append(controls);
      const svgNS = 'http://www.w3.org/2000/svg';
      const svg = document.createElementNS(svgNS, 'svg');
      svg.setAttribute('viewBox', '0 0 640 250');
      svg.setAttribute('class', 'topic-cluster-map');
      svg.setAttribute('role', 'group');
      svg.setAttribute('aria-label', 'Mapa de artigos: selecione um ponto para filtrar seu grupo');
      const points = data.points || [];
      const xs = points.map(p => p.x), ys = points.map(p => p.y);
      const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
      dots = points.map(point => {
        const dot = document.createElementNS(svgNS, 'circle');
        dot.setAttribute('cx', 30 + ((point.x - minX) / (maxX - minX || 1)) * 580);
        dot.setAttribute('cy', 25 + ((point.y - minY) / (maxY - minY || 1)) * 195);
        dot.setAttribute('r', '7'); dot.setAttribute('fill', color(point.topic_id));
        dot.setAttribute('tabindex', '0'); dot.setAttribute('role', 'button');
        const title = titles.get(point.pmid) || `PMID ${point.pmid}`;
        dot.setAttribute('aria-label', `${title}. Filtrar o grupo deste artigo.`);
        const tooltip = document.createElementNS(svgNS, 'title'); tooltip.textContent = title; dot.append(tooltip);
        const choose = () => filter(data.clusters.find(c => c.topic_id === point.topic_id));
        dot.addEventListener('click', choose);
        dot.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); } });
        svg.append(dot); return {dot, point};
      });
      panel.append(svg, element('p', 'Cada ponto representa um artigo. As cores indicam os temas; selecione um grupo para filtrar a lista. O mapa é uma projeção aproximada da similaridade entre títulos.', 'hint'), selection);
      data.clusters.forEach(cluster => {
        const members = new Set(cluster.pmids);
        cards.filter(card => members.has(card.dataset.pmid)).forEach(card => {
          const badge = element('span', cluster.is_outlier ? 'Sem grupo definido' : `Tema ${cluster.topic_id + 1}`, 'topic-cluster-badge');
          badge.style.setProperty('--cluster-color', color(cluster.topic_id));
          card.prepend(badge);
        });
      });
    } catch (error) {
      if (error.name !== 'AbortError' && panel.isConnected) status.textContent = error.message || 'Não foi possível agrupar os temas. Os artigos continuam disponíveis.';
    }
  };
})();
