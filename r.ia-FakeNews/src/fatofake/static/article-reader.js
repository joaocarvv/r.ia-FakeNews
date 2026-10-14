/* Leitor científico com navegação, busca e alegações criadas a partir do texto. */
(() => {
  const reader = document.getElementById('source-reader');
  const documentBody = document.getElementById('reader-document');
  const outline = document.getElementById('reader-outline');
  const reviewClaims = document.getElementById('review-claims');
  const status = document.getElementById('reader-status');
  const retry = document.getElementById('reader-retry');
  const searchInput = document.getElementById('reader-search-input');
  const searchCount = document.getElementById('reader-search-count');
  const progressBar = document.getElementById('reader-progress-bar');
  const customCount = document.getElementById('reader-custom-count');
  const claimPopup = document.createElement('div');
  claimPopup.id = 'claim-popover'; claimPopup.className = 'claim-popover'; claimPopup.hidden = true;
  claimPopup.setAttribute('role', 'dialog'); claimPopup.setAttribute('aria-label', 'Alegações no trecho');
  const selectionPopup = document.createElement('div');
  selectionPopup.id = 'reader-selection-popover'; selectionPopup.className = 'reader-selection-popover'; selectionPopup.hidden = true;
  selectionPopup.setAttribute('role', 'dialog'); selectionPopup.setAttribute('aria-label', 'Criar alegação a partir do trecho');
  document.body.append(claimPopup, selectionPopup);

  let currentJob, cachedSource, sourceId, generation = 0, claims = [];
  let claimAnchor, claimPinned = false, closeTimer, selectedContext = null;
  let searchHits = [], searchIndex = -1;
  let focusPlaceholder = null;
  function setFocusMode(enabled) {
    if (enabled && !focusPlaceholder) {
      // Keep fixed positioning independent of animated screen containers.
      focusPlaceholder = document.createComment('article-reader-position');
      reader.before(focusPlaceholder); document.body.append(reader);
    } else if (!enabled && focusPlaceholder) {
      focusPlaceholder.replaceWith(reader); focusPlaceholder = null;
    }
    reader.classList.toggle('is-focus-mode', enabled);
    document.body.classList.toggle('reader-focus-active', enabled);
    const button = document.getElementById('reader-focus');
    button.setAttribute('aria-pressed', String(enabled));
    button.textContent = enabled ? 'Sair do foco' : 'Modo foco';
  }
  const sizes = ['small', 'medium', 'large'];
  const element = (tag, text, cls) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  const controls = id => ({
    toggle: [...reviewClaims.querySelectorAll('input[type="checkbox"]')].find(node => node.dataset.claimId === id),
    editor: [...reviewClaims.querySelectorAll('textarea')].find(node => node.dataset.claimId === id)
  });
  const action = (text, handler) => {
    const button = element('button', text, 'secondary'); button.type = 'button';
    button.addEventListener('click', handler); return button;
  };
  const smooth = () => matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';

  function updateCustomCount() {
    const count = claims.filter(claim => claim.user_supplied).length;
    customCount.textContent = `${count} ${count === 1 ? 'alegação marcada' : 'alegações marcadas'}`;
  }

  function syncSelection() {
    documentBody.querySelectorAll('.source-highlight').forEach(mark => {
      const selected = JSON.parse(mark.dataset.claimIds || '[]').some(id => controls(id).toggle?.checked);
      mark.classList.toggle('is-selected', selected);
    });
  }

  window.closeClaimPopover = () => {
    clearTimeout(closeTimer); claimPopup.hidden = true; claimPinned = false;
    if (claimAnchor) claimAnchor.setAttribute('aria-expanded', 'false');
    claimAnchor = null;
  };
  function closeSelectionPopup({restoreFocus = false} = {}) {
    selectionPopup.hidden = true; selectedContext = null;
    getSelection()?.removeAllRanges();
    if (restoreFocus) documentBody.focus({preventScroll: true});
  }
  function positionFloating(node, rect) {
    node.style.left = `${Math.max(12, Math.min(rect.left, innerWidth - node.offsetWidth - 12))}px`;
    const below = rect.bottom + 10;
    const top = below + node.offsetHeight <= innerHeight - 12 ? below : rect.top - node.offsetHeight - 10;
    node.style.top = `${Math.max(12, top)}px`;
  }
  function positionClaimPopup() {
    if (!claimAnchor || claimPopup.hidden) return;
    positionFloating(claimPopup, claimAnchor.getBoundingClientRect());
  }

  function showClaimPopover(mark, pin = false, keyboard = false) {
    clearTimeout(closeTimer);
    if (!selectionPopup.hidden || !getSelection()?.isCollapsed) return;
    if (claimPinned && !pin) return;
    closeSelectionPopup();
    if (claimAnchor && claimAnchor !== mark) claimAnchor.setAttribute('aria-expanded', 'false');
    claimAnchor = mark; claimPinned = pin; claimPopup.replaceChildren();
    mark.setAttribute('aria-expanded', 'true');
    const close = action('Fechar', window.closeClaimPopover); close.classList.add('popover-close');
    claimPopup.append(close);
    JSON.parse(mark.dataset.claimIds || '[]').forEach(id => {
      const claim = claims.find(item => item.claim_id === id);
      const {toggle, editor} = controls(id);
      const card = element('section', '', 'popover-claim');
      card.append(element('span', claim?.user_supplied ? 'MARCADA POR VOCÊ' : 'ALEGAÇÃO EXTRAÍDA', 'kicker'));
      card.append(element('p', editor?.value || claim?.text || claim?.quote || ''));
      const actions = element('div', '', 'popover-actions');
      if (toggle && editor) {
        const select = action(toggle.checked ? 'Remover da seleção' : 'Selecionar alegação', () => {
          toggle.checked = !toggle.checked; toggle.dispatchEvent(new Event('change', {bubbles: true}));
          select.textContent = toggle.checked ? 'Remover da seleção' : 'Selecionar alegação';
        });
        actions.append(select, action('Editar', () => {
          closeClaimPopover(); editor.scrollIntoView({block: 'center', behavior: smooth()}); editor.focus();
        }));
      }
      card.append(actions); claimPopup.append(card);
    });
    claimPopup.hidden = false; positionClaimPopup();
    if (keyboard) close.focus();
  }
  const deferClose = () => { if (!claimPinned) closeTimer = setTimeout(closeClaimPopover, 180); };
  claimPopup.addEventListener('mouseenter', () => clearTimeout(closeTimer));
  claimPopup.addEventListener('mouseleave', deferClose);
  reviewClaims.addEventListener('change', syncSelection);

  function highlightedFragment(text, unit) {
    const ranges = [], located = new Set();
    claims.forEach(claim => {
      if (!claim.quote?.trim()) return;
      if (claim.page && unit.page && Number(claim.page) !== unit.page) return;
      if (claim.section && unit.section && claim.section !== unit.section) return;
      const expression = claim.quote.trim().split(/\s+/).map(part => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+');
      const regex = new RegExp(expression, 'gi');
      for (const match of text.matchAll(regex)) {
        ranges.push({start: match.index, end: match.index + match[0].length, id: claim.claim_id, user: claim.user_supplied});
        located.add(claim.claim_id);
      }
    });
    const points = [...new Set([0, text.length, ...ranges.flatMap(range => [range.start, range.end])])].sort((a, b) => a - b);
    const fragment = document.createDocumentFragment();
    for (let index = 0; index < points.length - 1; index++) {
      const start = points[index], end = points[index + 1];
      const matching = ranges.filter(range => range.start <= start && range.end >= end);
      const ids = [...new Set(matching.map(range => range.id))];
      const content = text.slice(start, end);
      if (!ids.length) { fragment.append(document.createTextNode(content)); continue; }
      const mark = element('mark', content, `source-highlight${matching.some(range => range.user) ? ' is-user-highlight' : ''}`);
      mark.dataset.claimIds = JSON.stringify(ids); mark.tabIndex = 0;
      mark.setAttribute('role', 'button'); mark.setAttribute('aria-haspopup', 'dialog');
      mark.setAttribute('aria-controls', claimPopup.id); mark.setAttribute('aria-expanded', 'false');
      mark.setAttribute('aria-label', `${ids.length === 1 ? 'Explorar alegação' : 'Explorar alegações'}: ${content}`);
      mark.addEventListener('mouseenter', event => { if (!event.buttons) showClaimPopover(mark); });
      mark.addEventListener('mouseleave', deferClose);
      mark.addEventListener('click', () => showClaimPopover(mark, true));
      mark.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); showClaimPopover(mark, true, true); }
      });
      fragment.append(mark);
    }
    return {fragment, located};
  }

  function sourceUnits(source) {
    if ((source.pages || []).length) return source.pages.map(item => ({
      key: `page-${item.page_number}`, label: `Página ${item.page_number}`, text: item.text || '', page: item.page_number, section: ''
    }));
    if ((source.sections || []).length) return source.sections.map((item, index) => ({
      key: `section-${index + 1}`, label: item.title || `Seção ${index + 1}`, text: item.text || '', page: null, section: item.title || ''
    }));
    const text = source.text || '';
    return text ? [{key: 'document', label: 'Texto disponível', text, page: null, section: ''}] : [];
  }

  function renderDocument(source, {keepSearch = true} = {}) {
    const units = sourceUnits(source);
    const located = new Set();
    documentBody.replaceChildren(); outline.replaceChildren();
    units.forEach((unit, index) => {
      const section = element('section', undefined, 'reader-unit');
      section.id = `reader-${unit.key}`; section.dataset.readerSection = unit.section || unit.label;
      if (unit.page) section.dataset.readerPage = String(unit.page);
      const heading = element('h3', unit.label, 'reader-unit-heading');
      const copy = element('div', undefined, 'reader-unit-text');
      const highlighted = highlightedFragment(unit.text, unit);
      highlighted.located.forEach(id => located.add(id)); copy.appendChild(highlighted.fragment);
      section.append(heading, copy); documentBody.appendChild(section);
      const link = action(unit.label, () => section.scrollIntoView({behavior: smooth(), block: 'start'}));
      link.className = 'reader-outline-link'; link.dataset.target = section.id;
      link.setAttribute('aria-current', index === 0 ? 'true' : 'false'); outline.appendChild(link);
    });
    syncSelection(); updateCustomCount();
    const quoted = claims.filter(claim => claim.quote?.trim());
    const missing = quoted.filter(claim => !located.has(claim.claim_id)).length;
    status.textContent = !units.length
      ? 'Não há texto extraído disponível para exibir.'
      : missing ? `${missing} alegação(ões) sem trecho literal localizado; elas continuam disponíveis na revisão.` : '';
    if (keepSearch && searchInput.value.trim()) applySearch(false);
  }

  function clearSearchMarks() {
    documentBody.querySelectorAll('.reader-search-hit').forEach(mark => mark.replaceWith(document.createTextNode(mark.textContent)));
    documentBody.normalize(); searchHits = []; searchIndex = -1;
    documentBody.querySelectorAll('.reader-unit.is-search-current').forEach(unit => unit.classList.remove('is-search-current'));
  }
  function applySearch(move = true) {
    clearSearchMarks();
    const query = searchInput.value.trim().toLocaleLowerCase('pt-BR');
    if (query.length < 2) { searchCount.textContent = ''; return; }
    const walker = document.createTreeWalker(documentBody, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) if (walker.currentNode.nodeValue.trim()) nodes.push(walker.currentNode);
    nodes.forEach(node => {
      const value = node.nodeValue, lower = value.toLocaleLowerCase('pt-BR');
      const positions = []; let start = 0;
      while ((start = lower.indexOf(query, start)) >= 0) { positions.push(start); start += query.length; }
      if (!positions.length) return;
      const fragment = document.createDocumentFragment(); let cursor = 0;
      positions.forEach(position => {
        fragment.append(document.createTextNode(value.slice(cursor, position)));
        const mark = element('mark', value.slice(position, position + query.length), 'reader-search-hit');
        fragment.append(mark); searchHits.push(mark); cursor = position + query.length;
      });
      fragment.append(document.createTextNode(value.slice(cursor))); node.replaceWith(fragment);
    });
    searchCount.textContent = searchHits.length ? `${searchHits.length} ocorrência(s)` : 'Nenhuma ocorrência';
    if (move && searchHits.length) showSearchHit(0);
  }
  function showSearchHit(index) {
    if (!searchHits.length) return;
    searchHits.forEach(hit => hit.classList.remove('is-current'));
    documentBody.querySelectorAll('.reader-unit.is-search-current').forEach(unit => unit.classList.remove('is-search-current'));
    searchIndex = (index + searchHits.length) % searchHits.length;
    const hit = searchHits[searchIndex]; hit.classList.add('is-current');
    hit.closest('.reader-unit')?.classList.add('is-search-current');
    searchCount.textContent = `${searchIndex + 1} de ${searchHits.length}`;
    hit.scrollIntoView({behavior: smooth(), block: 'center'});
  }

  function showSelectionPopup(range, context) {
    selectedContext = context; selectionPopup.replaceChildren();
    const heading = element('div', undefined, 'reader-selection-heading');
    heading.append(element('span', 'TRECHO SELECIONADO', 'kicker'), action('Fechar', () => closeSelectionPopup({restoreFocus: true})));
    const excerpt = element('blockquote', `“${context.quote}”`);
    const label = element('label', 'Alegação para comparar'); label.htmlFor = 'reader-selection-claim';
    const editor = document.createElement('textarea'); editor.id = 'reader-selection-claim'; editor.maxLength = 2000; editor.value = context.quote;
    const hint = element('p', 'Você pode editar a frase sem perder o vínculo com o trecho original.', 'hint');
    const actions = element('div', undefined, 'popover-actions');
    const add = action('Adicionar à comparação', () => {
      const text = editor.value.trim();
      if (text.length < 8 || text.length > 2000) { hint.textContent = 'Escreva uma alegação com 8 a 2.000 caracteres.'; editor.focus(); return; }
      const created = window.addUserClaim?.({...selectedContext, text});
      if (!created) { hint.textContent = 'Não foi possível adicionar a alegação enquanto outra análise está em andamento.'; return; }
      closeSelectionPopup();
      window.presentReaderNotice?.('Alegação adicionada. Revise-a na etapa “Alegações” antes de investigar.');
    });
    actions.append(add, action('Cancelar', () => closeSelectionPopup({restoreFocus: true})));
    selectionPopup.append(heading, excerpt, label, editor, hint, actions);
    selectionPopup.hidden = false; positionFloating(selectionPopup, range.getBoundingClientRect()); editor.focus({preventScroll: true}); editor.select();
  }

  function captureSelection() {
    if (!cachedSource || !selectionPopup.hidden) return;
    const selection = getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    if (!documentBody.contains(range.commonAncestorContainer)) return;
    const quote = selection.toString().replace(/\s+/g, ' ').trim();
    if (quote.length < 8 || quote.length > 4000) {
      if (quote.length > 4000) status.textContent = 'Selecione um trecho de até 4.000 caracteres.';
      return;
    }
    const origin = range.startContainer.nodeType === Node.TEXT_NODE ? range.startContainer.parentElement : range.startContainer;
    const unit = origin?.closest('.reader-unit');
    const end = range.endContainer.nodeType === Node.TEXT_NODE ? range.endContainer.parentElement : range.endContainer;
    if (!origin?.closest('.reader-unit-text') || origin.closest('.reader-unit-text') !== end?.closest('.reader-unit-text')) {
      status.textContent = 'Selecione um trecho dentro da mesma seção ou página para preservar sua localização.';
      return;
    }
    closeClaimPopover();
    showSelectionPopup(range, {
      quote,
      section: unit?.dataset.readerSection || '',
      page: unit?.dataset.readerPage ? Number(unit.dataset.readerPage) : null,
    });
  }

  function render(source) {
    const merged = new Map((source.claims || []).map(claim => [claim.claim_id, claim]));
    (currentJob?.result?.submitted_article?.claims || []).forEach(claim => merged.set(claim.claim_id, {...merged.get(claim.claim_id), ...claim}));
    claims.filter(claim => claim.user_supplied && controls(claim.claim_id).editor).forEach(claim => {
      merged.set(claim.claim_id, {...claim, text: controls(claim.claim_id).editor.value});
    });
    claims = [...merged.values()];
    document.getElementById('reader-title').textContent = source.title || 'Artigo enviado';
    const scope = source.content_scope || '';
    document.getElementById('reader-scope').textContent = scope === 'ABSTRACT_ONLY'
      ? 'Somente título e resumo (abstract). O texto completo não está disponível nesta análise.'
      : /FULL_TEXT/.test(scope) ? 'Texto extraído disponível na íntegra. A formatação pode diferir do documento original.'
      : 'Texto disponível da fonte. A cobertura do artigo completo não foi confirmada.';
    renderDocument(source, {keepSearch: false});
    reader.classList.toggle('reader-completed', currentJob?.status === 'SUCCEEDED');
    reader.open = true;
  }

  window.loadArticleReader = async (job, force = false) => {
    currentJob = job; reader.hidden = false; retry.hidden = true;
    closeClaimPopover(); closeSelectionPopup();
    if (sourceId === job.analysis_id && cachedSource && !force) { render(cachedSource); return; }
    const token = ++generation;
    if (sourceId !== job.analysis_id) claims = [];
    sourceId = job.analysis_id; cachedSource = null; documentBody.replaceChildren(); outline.replaceChildren();
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
    closeClaimPopover(); closeSelectionPopup(); reader.hidden = true; documentBody.replaceChildren(); outline.replaceChildren(); status.textContent = '';
    setFocusMode(false);
    searchInput.value = ''; searchCount.textContent = ''; searchHits = []; searchIndex = -1;
    progressBar.style.width = '0%'; updateCustomCount();
  };
  window.presentReaderNotice = message => {
    document.querySelector('.ui-toast[data-reader="true"]')?.remove();
    const toast = element('div', message, 'ui-toast'); toast.dataset.reader = 'true'; toast.setAttribute('role', 'status');
    document.body.appendChild(toast); setTimeout(() => toast.remove(), 5000);
  };

  documentBody.addEventListener('pointerup', () => setTimeout(captureSelection));
  documentBody.addEventListener('keyup', event => {
    if (event.key === 'Enter' || event.key === ' ' || event.key.startsWith('Arrow')) setTimeout(captureSelection);
  });
  document.addEventListener('pointerdown', event => {
    if (!claimPopup.contains(event.target) && !event.target.closest('.source-highlight')) closeClaimPopover();
    if (!selectionPopup.contains(event.target) && !documentBody.contains(event.target)) closeSelectionPopup();
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    if (!selectionPopup.hidden) closeSelectionPopup({restoreFocus: true});
    else if (!claimPopup.hidden) { const previous = claimAnchor; closeClaimPopover(); previous?.focus(); }
    else if (reader.classList.contains('is-focus-mode')) document.getElementById('reader-focus').click();
  });
  window.addEventListener('resize', positionClaimPopup);
  window.addEventListener('scroll', positionClaimPopup, true);
  window.addEventListener('fatofake:user-claim-added', event => {
    claims.push({...event.detail, user_supplied: true});
    if (cachedSource) renderDocument(cachedSource);
  });
  retry.addEventListener('click', () => { if (currentJob) loadArticleReader(currentJob, true); });
  searchInput.addEventListener('input', () => applySearch(true));
  document.getElementById('reader-search-next').addEventListener('click', () => showSearchHit(searchIndex + 1));
  document.getElementById('reader-font-decrease').addEventListener('click', () => {
    const index = Math.max(0, sizes.indexOf(reader.dataset.readerSize) - 1); reader.dataset.readerSize = sizes[index];
  });
  document.getElementById('reader-font-increase').addEventListener('click', () => {
    const index = Math.min(sizes.length - 1, sizes.indexOf(reader.dataset.readerSize) + 1); reader.dataset.readerSize = sizes[index];
  });
  document.querySelectorAll('.reader-theme').forEach(button => button.addEventListener('click', () => {
    reader.dataset.readerTheme = button.dataset.theme;
    document.querySelectorAll('.reader-theme').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  }));
  document.getElementById('reader-focus').addEventListener('click', () => setFocusMode(!reader.classList.contains('is-focus-mode')));
  documentBody.addEventListener('scroll', () => {
    const maximum = documentBody.scrollHeight - documentBody.clientHeight;
    progressBar.style.width = `${maximum > 0 ? Math.round((documentBody.scrollTop / maximum) * 100) : 100}%`;
    const units = [...documentBody.querySelectorAll('.reader-unit')];
    if (!units.length) return;
    const top = documentBody.getBoundingClientRect().top + 24;
    const current = units.reduce((best, unit) => unit.getBoundingClientRect().top <= top ? unit : best, units[0]);
    outline.querySelectorAll('.reader-outline-link').forEach(link => link.setAttribute('aria-current', String(link.dataset.target === current.id)));
  });
})();
