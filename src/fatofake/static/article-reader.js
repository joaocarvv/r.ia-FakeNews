/* The original document and the editable claims remain separate. */
(() => {
  const reader = document.getElementById('source-reader');
  const documentBody = document.getElementById('reader-document');
  const sidebar = document.getElementById('reader-sidebar');
  sidebar.appendChild(document.getElementById('claim-review'));
  const status = document.getElementById('reader-status');
  const retry = document.getElementById('reader-retry');
  const popup = document.createElement('div');
  popup.id = 'claim-popover'; popup.className = 'claim-popover'; popup.hidden = true;
  popup.setAttribute('role', 'dialog'); popup.setAttribute('aria-label', 'Alegações no trecho');
  document.body.appendChild(popup);
  let currentJob, cachedSource, sourceId, generation = 0, claims = [], anchor, pinned = false, closeTimer;
  const element = (tag, text, cls) => {
    const node = document.createElement(tag); node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  const controls = id => ({
    toggle: [...sidebar.querySelectorAll('input[type="checkbox"]')].find(node => node.dataset.claimId === id),
    editor: [...sidebar.querySelectorAll('textarea')].find(node => node.dataset.claimId === id)
  });
  function syncSelection() {
    documentBody.querySelectorAll('mark').forEach(mark => {
      const selected = JSON.parse(mark.dataset.claimIds).some(id => controls(id).toggle?.checked);
      mark.classList.toggle('is-selected', selected);
    });
  }
  window.closeClaimPopover = () => {
    clearTimeout(closeTimer); popup.hidden = true; pinned = false;
    if (anchor) anchor.setAttribute('aria-expanded', 'false');
    anchor = null;
  };
  function positionPopup() {
    if (!anchor || popup.hidden) return;
    const rect = anchor.getBoundingClientRect();
    popup.style.left = `${Math.max(12, Math.min(rect.left, innerWidth - popup.offsetWidth - 12))}px`;
    const below = rect.bottom + 8;
    popup.style.top = `${Math.max(12, Math.min(below, innerHeight - popup.offsetHeight - 12))}px`;
  }
  function action(text, handler) {
    const button = element('button', text, 'secondary'); button.type = 'button';
    button.addEventListener('click', handler); return button;
  }
  function showPopover(mark, pin = false, keyboard = false) {
    clearTimeout(closeTimer);
    if (pinned && !pin) return;
    if (anchor && anchor !== mark) anchor.setAttribute('aria-expanded', 'false');
    anchor = mark; pinned = pin; popup.replaceChildren();
    mark.setAttribute('aria-expanded', 'true');
    const close = action('Fechar', window.closeClaimPopover); close.classList.add('popover-close');
    popup.append(close);
    JSON.parse(mark.dataset.claimIds).forEach(id => {
      const claim = claims.find(item => item.claim_id === id);
      const {toggle, editor} = controls(id);
      const card = element('section', '', 'popover-claim');
      card.append(element('span', 'ALEGAÇÃO EXTRAÍDA', 'kicker'));
      card.append(element('p', editor?.value || claim?.text || claim?.quote || ''));
      const actions = element('div', '', 'popover-actions');
      if (currentJob?.status !== 'SUCCEEDED' && toggle && editor) {
        const select = action(toggle.checked ? 'Remover da seleção' : 'Selecionar alegação', () => {
          if (researchSelected.disabled) return;
          toggle.checked = !toggle.checked; toggle.dispatchEvent(new Event('change', {bubbles: true}));
          select.textContent = toggle.checked ? 'Remover da seleção' : 'Selecionar alegação';
        });
        actions.append(select, action('Editar', () => {
          closeClaimPopover(); editor.scrollIntoView({block: 'center', behavior: 'smooth'}); editor.focus();
        }), action('Investigar esta alegação', () => {
          if (researchSelected.disabled) return;
          closeClaimPopover(); startResearch([{claim_id: id, text: editor.value.trim()}]);
        }));
      } else {
        const analyses = (currentJob?.result?.claim_analyses || []).filter(item => item.status === 'SUCCEEDED' && item.result);
        const index = analyses.findIndex(item => item.claim_id === id || item.claim?.claim_id === id);
        if (index >= 0) actions.append(action('Ver comparação', () => {
          closeClaimPopover(); document.querySelectorAll('#claim-tabs button')[index]?.click();
          document.getElementById('result').scrollIntoView({behavior: 'smooth'});
        }));
        else actions.append(element('small', 'Este trecho permanece disponível para consulta no artigo.'));
      }
      card.append(actions); popup.append(card);
    });
    popup.hidden = false; positionPopup();
    if (keyboard) close.focus();
  }
  const deferClose = () => {
    if (!pinned) closeTimer = setTimeout(closeClaimPopover, 180);
  };
  popup.addEventListener('mouseenter', () => clearTimeout(closeTimer));
  popup.addEventListener('mouseleave', deferClose);
  document.addEventListener('pointerdown', event => {
    if (!popup.contains(event.target) && !event.target.closest('.source-highlight')) closeClaimPopover();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !popup.hidden) {
      const previous = anchor; closeClaimPopover(); previous?.focus();
    }
  });
  window.addEventListener('resize', positionPopup);
  window.addEventListener('scroll', positionPopup, true);
  sidebar.addEventListener('change', syncSelection);
  function highlight(text) {
    const ranges = [], located = new Set();
    claims.forEach(claim => {
      if (!claim.quote?.trim()) return;
      const expression = claim.quote.trim().split(/\s+/).map(part => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+');
      const regex = new RegExp(expression, 'g');
      for (const match of text.matchAll(regex)) {
        ranges.push({start: match.index, end: match.index + match[0].length, id: claim.claim_id});
        located.add(claim.claim_id);
      }
    });
    const points = [...new Set([0, text.length, ...ranges.flatMap(range => [range.start, range.end])])].sort((a,b) => a-b);
    const fragment = document.createDocumentFragment();
    for (let i = 0; i < points.length - 1; i++) {
      const start = points[i], end = points[i+1];
      const ids = [...new Set(ranges.filter(range => range.start <= start && range.end >= end).map(range => range.id))];
      const content = text.slice(start, end);
      if (!ids.length) { fragment.append(document.createTextNode(content)); continue; }
      const mark = element('mark', content, 'source-highlight');
      mark.dataset.claimIds = JSON.stringify(ids); mark.tabIndex = 0;
      mark.setAttribute('role', 'button'); mark.setAttribute('aria-haspopup', 'dialog');
      mark.setAttribute('aria-controls', popup.id); mark.setAttribute('aria-expanded', 'false');
      mark.setAttribute('aria-label', `${ids.length === 1 ? 'Explorar alegação' : 'Explorar alegações'}: ${content}`);
      mark.addEventListener('mouseenter', () => showPopover(mark));
      mark.addEventListener('mouseleave', deferClose);
      mark.addEventListener('click', () => showPopover(mark, true));
      mark.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); showPopover(mark, true, true); }
      });
      fragment.append(mark);
    }
    documentBody.replaceChildren(fragment); syncSelection();
    const missing = claims.length - located.size;
    status.textContent = missing ? `${missing} alegação(ões) sem trecho literal localizado neste texto. Você pode revisá-las na lista; não foram marcadas por aproximação.` : '';
  }
  function render(source) {
    const merged = new Map((source.claims || []).map(claim => [claim.claim_id, claim]));
    (currentJob?.result?.submitted_article?.claims || []).forEach(claim => merged.set(claim.claim_id, {...merged.get(claim.claim_id), ...claim}));
    claims = [...merged.values()];
    document.getElementById('reader-title').textContent = source.title || 'Artigo enviado';
    const scope = source.content_scope || '';
    document.getElementById('reader-scope').textContent = scope === 'ABSTRACT_ONLY'
      ? 'Somente título e resumo (abstract). O texto completo não está disponível nesta análise.'
      : /FULL_TEXT/.test(scope) ? 'Texto extraído disponível na íntegra. A formatação pode diferir do documento original.'
      : 'Texto disponível da fonte. A cobertura do artigo completo não foi confirmada.';
    const text = source.text || (source.pages || []).map(page => page.text || '').join('\n\n') || (source.sections || []).map(section => `${section.title || ''}\n${section.text || ''}`).join('\n\n');
    highlight(text);
    if (!text.trim()) status.textContent = 'Não há texto extraído disponível para exibir. As alegações podem ser revisadas na lista.';
    const completed = currentJob?.status === 'SUCCEEDED';
    reader.classList.toggle('reader-completed', completed);
    reader.open = !completed;
  }
  window.loadArticleReader = async (job, force = false) => {
    currentJob = job; reader.hidden = false; retry.hidden = true;
    closeClaimPopover();
    if (sourceId === job.analysis_id && cachedSource && !force) { render(cachedSource); return; }
    const token = ++generation;
    sourceId = job.analysis_id; cachedSource = null; documentBody.replaceChildren();
    status.textContent = 'Carregando o texto do artigo…'; reader.open = true;
    try {
      const response = await fetch(`/api/v1/analyses/${encodeURIComponent(job.analysis_id)}/source`);
      if (!response.ok) throw new Error('Não foi possível carregar o texto do artigo.');
      const source = await response.json();
      if (token !== generation) return;
      cachedSource = source; render(source);
    } catch (error) {
      if (token !== generation) return;
      status.textContent = error.message; retry.hidden = false;
    }
  };
  window.resetArticleReader = () => {
    generation++; currentJob = null; sourceId = null; cachedSource = null; claims = [];
    closeClaimPopover(); reader.hidden = true; documentBody.replaceChildren(); status.textContent = '';
  };
  retry.addEventListener('click', () => { if (currentJob) loadArticleReader(currentJob, true); });
})();
