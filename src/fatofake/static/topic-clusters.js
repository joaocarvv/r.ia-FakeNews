(() => {
  let activeController = null;
  const batchSize = 8;
  const colors = ['#da5d32', '#28725a', '#6e63b6', '#b47a28', '#267f91', '#a34d70', '#567247'];
  const color = id => id < 0 ? '#9aa3a0' : colors[id % colors.length];
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const shortTitle = value => value.length > 58 ? `${value.slice(0, 55)}…` : value;

  async function request(controller, body) {
    const response = await fetch('/api/v1/pubmed-clusters', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      signal: controller.signal,
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || 'Grupos de temas indisponíveis.');
    return data;
  }

  function graphView(data, articles, filter) {
    const shell = element('div', undefined, 'topic-graph-shell');
    const graphPanel = element('div', undefined, 'topic-graph-panel');
    const graphHeader = element('div', undefined, 'topic-graph-heading');
    graphHeader.append(element('strong', 'Mapa de relações'), element('span', 'Posições fixas para comparação'));
    graphPanel.appendChild(graphHeader);

    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('viewBox', '0 0 720 420');
    svg.setAttribute('class', 'topic-cluster-map');
    svg.setAttribute('role', 'group');
    svg.setAttribute('aria-label', 'Grafo dos artigos por similaridade e tema');
    const points = data.points || [];
    const xs = points.map(point => point.x);
    const ys = points.map(point => point.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const positions = new Map(points.map(point => [point.pmid, {
      x: 55 + ((point.x - minX) / (maxX - minX || 1)) * 610,
      y: 48 + ((point.y - minY) / (maxY - minY || 1)) * 320,
      topicId: point.topic_id,
    }]));
    const articleByPmid = new Map(articles.map(article => [article.pmid, article]));
    const edgeLayer = document.createElementNS(svgNS, 'g');
    edgeLayer.setAttribute('class', 'topic-graph-edges');
    const nodeLayer = document.createElementNS(svgNS, 'g');
    nodeLayer.setAttribute('class', 'topic-graph-nodes');
    svg.append(edgeLayer, nodeLayer);

    const edgeNodes = (data.edges || []).map(edge => {
      const line = document.createElementNS(svgNS, 'line');
      line.dataset.source = edge.source;
      line.dataset.target = edge.target;
      line.dataset.sameTopic = String(edge.same_topic);
      line.setAttribute('stroke-width', String(1 + Math.max(0, edge.similarity) * 2));
      const title = document.createElementNS(svgNS, 'title');
      title.textContent = `Similaridade ${(edge.similarity * 100).toFixed(0)}%`;
      line.appendChild(title);
      edgeLayer.appendChild(line);
      return {edge, line};
    });
    const nodeNodes = [];

    const updatePosition = pmid => {
      const position = positions.get(pmid);
      const current = nodeNodes.find(item => item.point.pmid === pmid);
      if (current) current.group.setAttribute('transform', `translate(${position.x} ${position.y})`);
      edgeNodes.forEach(({edge, line}) => {
        if (edge.source !== pmid && edge.target !== pmid) return;
        const source = positions.get(edge.source), target = positions.get(edge.target);
        line.setAttribute('x1', source.x); line.setAttribute('y1', source.y);
        line.setAttribute('x2', target.x); line.setAttribute('y2', target.y);
      });
    };

    let visibleMembers = null;
    const connectedTo = pmid => new Set((data.edges || []).flatMap(edge => {
      if (edge.source === pmid) return [edge.source, edge.target];
      if (edge.target === pmid) return [edge.source, edge.target];
      return [];
    }));
    const emphasize = pmid => {
      const connected = pmid ? connectedTo(pmid) : null;
      nodeNodes.forEach(({point, group}) => {
        const selected = !visibleMembers || visibleMembers.has(point.pmid);
        const related = !connected || connected.has(point.pmid);
        group.setAttribute('opacity', selected && related ? '1' : '.16');
      });
      edgeNodes.forEach(({edge, line}) => {
        const selected = !visibleMembers || visibleMembers.has(edge.source) || visibleMembers.has(edge.target);
        const related = !connected || edge.source === pmid || edge.target === pmid;
        line.setAttribute('opacity', selected && related ? '1' : '.08');
      });
    };
    const setMembers = members => { visibleMembers = members; emphasize(null); };

    points.forEach(point => {
      const article = articleByPmid.get(point.pmid);
      const group = document.createElementNS(svgNS, 'g');
      group.setAttribute('class', 'topic-graph-node');
      group.setAttribute('tabindex', '0');
      group.setAttribute('role', 'button');
      group.setAttribute('aria-label', `${article?.title_pt || article?.title || `PMID ${point.pmid}`}. Selecionar tema.`);
      const halo = document.createElementNS(svgNS, 'circle');
      halo.setAttribute('r', '15'); halo.setAttribute('class', 'topic-node-halo');
      const dot = document.createElementNS(svgNS, 'circle');
      dot.setAttribute('r', '8'); dot.setAttribute('fill', color(point.topic_id));
      const label = document.createElementNS(svgNS, 'text');
      label.setAttribute('x', '13'); label.setAttribute('y', '4');
      label.textContent = `PMID ${point.pmid}`;
      const title = document.createElementNS(svgNS, 'title');
      title.textContent = article?.title_pt || article?.title || `PMID ${point.pmid}`;
      group.append(halo, dot, label, title);
      nodeLayer.appendChild(group);
      nodeNodes.push({point, group});
      updatePosition(point.pmid);

      group.addEventListener('mouseenter', () => emphasize(point.pmid));
      group.addEventListener('mouseleave', () => emphasize(null));
      group.addEventListener('focus', () => emphasize(point.pmid));
      group.addEventListener('blur', () => emphasize(null));
      const choose = () => filter(data.clusters.find(cluster => cluster.topic_id === point.topic_id));
      group.addEventListener('click', choose);
      group.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); }
      });
    });
    edgeNodes.forEach(({edge}) => { updatePosition(edge.source); updatePosition(edge.target); });
    const threshold = Math.round((data.edge_similarity_threshold || 0.42) * 100);
    graphPanel.append(svg, element('p', `As linhas aparecem somente quando a similaridade entre títulos atinge pelo menos ${threshold}%. A posição é uma projeção fixa e aproximada; proximidade não significa qualidade nem concordância científica.`, 'hint'));
    const memberPanel = element('aside', undefined, 'topic-cluster-articles');
    shell.append(graphPanel, memberPanel);
    return {shell, memberPanel, setMembers};
  }

  window.cancelPubmedClusters = () => {
    activeController?.abort();
    activeController = null;
  };

  window.showPubmedClusters = async (articles, results, options = {}) => {
    window.cancelPubmedClusters();
    const controller = new AbortController();
    activeController = controller;
    const panel = element('section', undefined, 'topic-clusters');
    panel.setAttribute('aria-label', 'Grupos de temas dos artigos');
    const heading = element('div', undefined, 'topic-clusters-heading');
    const headingCopy = element('div');
    headingCopy.append(element('span', 'BERTopic incremental', 'section-eyebrow'), element('h3', 'Explore os artigos por tema'));
    heading.appendChild(headingCopy);
    const status = element('p', `Preparando 0 de ${articles.length} artigos…`, 'topic-cluster-status');
    status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    heading.appendChild(status); panel.appendChild(heading);

    const loader = element('div', undefined, 'topic-cluster-loader');
    const progress = element('div', undefined, 'topic-cluster-progress');
    const progressBar = element('span'); progress.appendChild(progressBar);
    const queue = element('div', undefined, 'topic-cluster-queue');
    const queueItems = articles.map(article => {
      const item = element('span', shortTitle(article.title_pt || article.title));
      item.title = article.title_pt || article.title;
      queue.appendChild(item); return item;
    });
    loader.append(progress, queue); panel.appendChild(loader);
    results.prepend(panel);

    const payloadArticles = articles.map(({pmid, title}) => ({pmid, title}));
    try {
      for (let offset = 0; offset < payloadArticles.length; offset += batchSize) {
        const batch = payloadArticles.slice(offset, offset + batchSize);
        await request(controller, {mode: 'prepare', articles: batch});
        if (controller.signal.aborted || !panel.isConnected) return;
        const prepared = Math.min(offset + batch.length, payloadArticles.length);
        queueItems.slice(offset, prepared).forEach(item => item.classList.add('is-ready'));
        progressBar.style.width = `${Math.round((prepared / payloadArticles.length) * 76)}%`;
        status.textContent = `Embeddings preparados: ${prepared} de ${payloadArticles.length}`;
      }
      status.textContent = 'Ajustando os temas e construindo as relações…';
      progressBar.style.width = '88%';
      let data = await request(controller, {mode: 'cluster', articles: payloadArticles});
      if (controller.signal.aborted || !panel.isConnected) return;
      if (data.status !== 'available') {
        status.textContent = data.message || 'Não há artigos suficientes para agrupar os temas.';
        loader.classList.add('is-complete'); progressBar.style.width = '100%';
        return;
      }
      if (options.enrich && data.llm_available) {
        status.textContent = 'A IA está revisando artigos sem grupo e resumindo os temas…';
        progressBar.style.width = '94%';
        data = await request(controller, {mode: 'enrich', articles: payloadArticles});
        if (controller.signal.aborted || !panel.isConnected) return;
      } else if (options.enrich) {
        data.enrichment_status = 'unavailable';
        data.enrichment_message = 'Resumos por IA desativados: configure GEMINI_API_KEY no arquivo .env e reinicie a aplicação.';
      }
      progressBar.style.width = '100%'; loader.classList.add('is-complete');
      status.textContent = `${data.topic_count} tema(s) · ${data.document_count} artigos · ${data.duration_ms} ms`;
      if (data.fallback_used) {
        const notice = element('p', 'O HDBSCAN considerou a maior parte dos títulos como ruído. O mapa aplicou um particionamento adaptativo sobre os mesmos embeddings para evitar um resultado vazio.', 'topic-cluster-notice');
        panel.appendChild(notice);
      }

      const cards = () => Array.from((options.cardsRoot || results).querySelectorAll('.topic-card'));
      const articleByPmid = new Map(articles.map(article => [article.pmid, article]));
      const controls = element('div', undefined, 'topic-cluster-controls');
      const selection = element('p', `Exibindo todos os ${articles.length} artigos.`, 'topic-cluster-selection');
      selection.setAttribute('role', 'status');
      const buttons = [];
      let graph;

      const renderMembers = cluster => {
        const memberPanel = graph.memberPanel;
        memberPanel.replaceChildren();
        memberPanel.append(element('span', cluster ? 'ARTIGOS DO TEMA' : 'TODOS OS ARTIGOS', 'section-eyebrow'));
        memberPanel.append(element('h4', cluster?.label || `${articles.length} artigos no mapa`));
        if (cluster?.summary) memberPanel.append(element('p', cluster.summary, 'topic-cluster-description'));
        const list = element('div', undefined, 'topic-cluster-member-list');
        const pmids = cluster?.pmids || articles.map(article => article.pmid);
        pmids.forEach(pmid => {
          const article = articleByPmid.get(pmid);
          if (!article) return;
          const button = element('button', undefined, 'topic-cluster-member');
          button.type = 'button';
          button.append(element('span', article.title_pt || article.title), element('small', `PMID ${pmid}`));
          button.addEventListener('click', () => {
            const card = cards().find(item => item.dataset.pmid === pmid);
            card?.scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center'});
            card?.animate([{boxShadow: '0 0 0 0 rgba(218,93,50,0)'}, {boxShadow: '0 0 0 4px rgba(218,93,50,.2)'}, {boxShadow: '0 0 0 0 rgba(218,93,50,0)'}], {duration: 1100});
          });
          list.appendChild(button);
        });
        memberPanel.appendChild(list);
      };

      const filter = cluster => {
        const members = cluster ? new Set(cluster.pmids) : null;
        cards().forEach(card => { card.hidden = Boolean(members) && !members.has(card.dataset.pmid); });
        buttons.forEach(item => item.button.setAttribute('aria-pressed', String(item.topicId === (cluster?.topic_id ?? null))));
        graph.setMembers(members);
        selection.textContent = cluster ? `${cluster.count} artigo(s) em ${cluster.label}.` : `Exibindo todos os ${articles.length} artigos.`;
        renderMembers(cluster);
      };

      const all = element('button', `Todos · ${articles.length}`, 'secondary topic-cluster-button');
      all.type = 'button'; all.setAttribute('aria-pressed', 'true');
      all.addEventListener('click', () => filter(null));
      buttons.push({button: all, topicId: null}); controls.appendChild(all);
      data.clusters.forEach(cluster => {
        const button = element('button', undefined, 'secondary topic-cluster-button');
        button.type = 'button'; button.setAttribute('aria-pressed', 'false');
        button.style.setProperty('--cluster-color', color(cluster.topic_id));
        button.append(element('strong', cluster.is_outlier ? 'Sem grupo definido' : `Tema ${cluster.topic_id + 1} · ${cluster.count}`));
        button.append(element('span', cluster.is_outlier ? `${cluster.count} artigo(s)` : cluster.label));
        if (cluster.summary) button.append(element('small', cluster.summary, 'topic-cluster-summary'));
        button.title = (cluster.terms || []).join(', ');
        button.addEventListener('click', () => filter(cluster));
        buttons.push({button, topicId: cluster.topic_id}); controls.appendChild(button);
      });
      panel.append(controls, selection);
      graph = graphView(data, articles, filter);
      panel.appendChild(graph.shell);
      renderMembers(null);

      if (data.enrichment_status === 'unavailable') {
        panel.appendChild(element('p', data.enrichment_message || 'Os temas foram calculados sem a revisão da IA.', 'topic-cluster-notice'));
      } else if (data.llm_enriched) {
        const reviewed = data.llm_reassigned_count || 0;
        const others = data.llm_other_count || 0;
        panel.appendChild(element('p', `Revisão por IA concluída: ${reviewed} artigo(s) realocado(s) e ${others} mantido(s) no grupo Outros. Os resumos descrevem os títulos e não avaliam a qualidade dos estudos.`, 'topic-cluster-ai-note'));
      }

      data.clusters.forEach(cluster => {
        const members = new Set(cluster.pmids);
        cards().filter(card => members.has(card.dataset.pmid)).forEach(card => {
          const badge = element('span', cluster.is_outlier ? 'Sem grupo definido' : `Tema ${cluster.topic_id + 1}`, 'topic-cluster-badge');
          badge.style.setProperty('--cluster-color', color(cluster.topic_id));
          card.prepend(badge);
        });
      });
      const limitation = element('p', data.limitation, 'hint');
      panel.appendChild(limitation);
    } catch (error) {
      if (error.name !== 'AbortError' && panel.isConnected) {
        status.textContent = error.message || 'Não foi possível agrupar os temas. Os artigos continuam disponíveis.';
        loader.classList.add('has-error');
      }
    }
  };
})();
