/* Screen-based workspace built over the existing API and rendering contracts. */
(function () {
  const main = document.getElementById('workspace');
  const topbar = main.querySelector('.topbar');
  const footer = main.querySelector('footer');
  const preview = document.getElementById('preview-dialog');
  const breadcrumb = document.getElementById('screen-breadcrumb');
  const analysisNav = document.getElementById('analysis-nav');
  const screens = {};
  let activeScreen = 'home';
  let analysisAvailable = false;
  let claimsAvailable = false;
  let resultsAvailable = false;
  let homeEntry = null;
  const screenHashes = {home: 'inicio', processing: 'processamento', reading: 'leitura', claims: 'alegacoes', results: 'resultados', library: 'biblioteca'};

  function heading(kicker, title, description, meta) {
    const header = document.createElement('header');
    header.className = 'screen-heading';
    const copy = document.createElement('div');
    copy.className = 'screen-heading-copy';
    const eyebrow = document.createElement('p');
    eyebrow.className = 'screen-kicker';
    eyebrow.textContent = kicker;
    const headingNode = document.createElement('h1');
    headingNode.textContent = title;
    const paragraph = document.createElement('p');
    paragraph.textContent = description;
    copy.append(eyebrow, headingNode, paragraph);
    header.appendChild(copy);
    if (meta) {
      const badge = document.createElement('span');
      badge.className = 'screen-meta';
      badge.textContent = meta;
      header.appendChild(badge);
    }
    return header;
  }

  function createScreen(name, label) {
    const screen = document.createElement('section');
    screen.id = `screen-${name}`;
    screen.className = 'app-screen';
    screen.dataset.screen = name;
    screen.setAttribute('aria-label', label);
    main.insertBefore(screen, preview);
    screens[name] = screen;
    return screen;
  }

  const home = createScreen('home', 'Início e escolha da fonte');
  const processing = createScreen('processing', 'Processamento da análise');
  const reading = createScreen('reading', 'Leitura organizada do artigo');
  const claims = createScreen('claims', 'Revisão das alegações');
  const results = createScreen('results', 'Resultados da investigação');
  const library = createScreen('library', 'Biblioteca de artigos');

  const workspaceHeader = main.querySelector('.workspace-header');
  const workflow = main.querySelector('.workflow');
  const entry = main.querySelector('.entry-workspace');
  const safety = main.querySelector('.safety-note');
  home.append(workspaceHeader, workflow, entry, safety);

  processing.append(
    heading('Análise em andamento', 'Estamos organizando as evidências.', 'Acompanhe cada etapa da leitura. Você pode deixar esta tela aberta enquanto o artigo é processado.', 'Processamento local')
  );
  const processingGrid = document.createElement('div');
  processingGrid.className = 'processing-stage';
  const processingMain = document.createElement('div');
  processingMain.className = 'screen-panel';
  processingMain.append(document.getElementById('status'), document.getElementById('error'));
  const processingAside = document.createElement('aside');
  processingAside.className = 'processing-aside screen-panel';
  processingAside.innerHTML = '<strong>O que acontece agora?</strong><p>A fonte é preparada, o texto é estruturado e as alegações são associadas aos trechos originais antes de qualquer comparação.</p><p>Quando o texto completo não estiver disponível, a limitação aparecerá explicitamente no resultado.</p>';
  processingGrid.append(processingMain, processingAside);
  processing.appendChild(processingGrid);

  reading.append(
    heading('Leitura da fonte', 'Seu artigo, organizado.', 'Confira o objetivo, o desenho do estudo, os resultados e os trechos originais antes de escolher o que investigar.', 'Etapa 1 de 3')
  );
  reading.append(document.getElementById('whole-article-report'), document.getElementById('source-reader'));
  const readingActions = document.createElement('div');
  readingActions.className = 'reading-actions';
  const reviewButton = document.createElement('button');
  reviewButton.type = 'button';
  reviewButton.textContent = 'Revisar alegações';
  reviewButton.addEventListener('click', () => showScreen('claims'));
  readingActions.appendChild(reviewButton);
  reading.appendChild(readingActions);

  claims.append(
    heading('Revisão humana', 'Escolha o que deseja investigar.', 'Edite as afirmações, selecione as alegações e defina como a comparação será feita.', 'Etapa 2 de 3')
  );
  const claimsLayout = document.createElement('div');
  claimsLayout.className = 'claims-layout';
  claimsLayout.append(document.getElementById('claim-review'));
  const claimsSummary = document.createElement('aside');
  claimsSummary.className = 'panel claims-summary';
  claimsSummary.innerHTML = '<h3>Resumo da investigação</h3><ul class="claims-summary-list"><li><span>Fonte</span><strong>PubMed / PMC</strong></li><li><span>Comparação</span><strong id="screen-comparison-mode">Automática</strong></li><li><span>Profundidade</span><strong id="screen-depth-mode">Rápida</strong></li></ul><p class="hint">A busca usa somente as alegações selecionadas. Você poderá conferir cada artigo e trecho no resultado.</p>';
  claimsLayout.appendChild(claimsSummary);
  claims.append(document.getElementById('claim-pipeline'), claimsLayout);

  results.append(
    heading('Síntese e conferência', 'Evidências para conferir.', 'Comece pela visão geral e aprofunde nos estudos, nas fontes e no método usado para reproduzir a busca.', 'Etapa 3 de 3')
  );
  const resultNav = document.createElement('nav');
  resultNav.className = 'result-nav';
  resultNav.setAttribute('aria-label', 'Seções dos resultados');
  const resultSections = [
    ['Visão geral', 'headline'],
    ['Evidências', 'table-title'],
    ['Estudos e fontes', 'findings'],
    ['Atualizações', 'updates-title'],
    ['Método', 'crossing-title']
  ];
  resultSections.forEach(([label, target], index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.classList.toggle('is-active', index === 0);
    button.addEventListener('click', () => {
      document.getElementById(target)?.scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start'});
      resultNav.querySelectorAll('button').forEach(item => item.classList.toggle('is-active', item === button));
    });
    resultNav.appendChild(button);
  });
  results.append(resultNav, document.getElementById('result'));

  library.append(
    heading('Acervo de pesquisa', 'Sua biblioteca científica.', 'Encontre artigos salvos, continue análises e organize referências para comparações manuais.', 'Armazenamento local')
  );
  const libraryPanel = document.getElementById('article-library');
  const libraryStats = document.createElement('div');
  libraryStats.className = 'library-toolbar-note';
  libraryStats.innerHTML = '<div class="library-stat"><strong id="library-total-stat">—</strong><span>ARTIGOS GUARDADOS</span></div><div class="library-stat"><strong>PDF + PMID</strong><span>FONTES ACEITAS</span></div><div class="library-stat"><strong>Local</strong><span>DADOS DESTA INSTALAÇÃO</span></div>';
  libraryPanel.insertBefore(libraryStats, libraryPanel.querySelector('.actions'));
  library.appendChild(libraryPanel);

  function canOpen(name) {
    if (name === 'reading') return analysisAvailable;
    if (name === 'claims') return claimsAvailable;
    if (name === 'results') return resultsAvailable;
    return true;
  }

  function updateNav(name) {
    document.querySelectorAll('[data-screen-nav]').forEach(item => {
      let active = item.dataset.screenNav === name;
      if (name === 'home') {
        active = homeEntry ? item.dataset.entry === homeEntry : item.id === 'home-open';
      }
      item.classList.toggle('is-active', active);
    });
    document.querySelectorAll('#analysis-nav [data-screen-nav]').forEach(item => {
      item.disabled = !canOpen(item.dataset.screenNav);
    });
    analysisNav.hidden = !analysisAvailable;
    const labels = {home: 'Início', processing: 'Processamento', reading: 'Leitura', claims: 'Alegações', results: 'Resultados', library: 'Biblioteca'};
    breadcrumb.textContent = labels[name] || 'Pesquisa científica';
  }

  function showScreen(name, options = {}) {
    if (!screens[name] || (!canOpen(name) && !options.force)) return;
    activeScreen = name;
    Object.entries(screens).forEach(([key, screen]) => {
      const active = key === name;
      screen.classList.toggle('is-active', active);
      screen.setAttribute('aria-hidden', String(!active));
    });
    updateNav(name);
    if (!options.preserveHash && screenHashes[name] && location.hash !== `#${screenHashes[name]}`) {
      history.replaceState(null, '', `#${screenHashes[name]}`);
    }
    if (!options.preserveScroll) window.scrollTo({top: 0, behavior: options.instant ? 'auto' : 'smooth'});
  }

  document.querySelectorAll('[data-screen-nav]').forEach(item => {
    item.addEventListener('click', event => {
      const target = item.dataset.screenNav;
      if (!target) return;
      event.preventDefault();
      if (target === 'home') {
        homeEntry = item.dataset.entry || null;
        if (item.dataset.entry) setInputMode(item.dataset.entry, true);
      }
      showScreen(target);
      if (target === 'library' && typeof window.refreshArticleLibrary === 'function') window.refreshArticleLibrary();
    });
  });
  document.querySelectorAll('a[href="#article-library"]').forEach(link => {
    if (link.dataset.screenNav) return;
    link.addEventListener('click', event => {
      event.preventDefault();
      showScreen('library');
      if (typeof window.refreshArticleLibrary === 'function') window.refreshArticleLibrary();
    });
  });

  document.querySelectorAll('input[name="comparison-mode"]').forEach(input => input.addEventListener('change', () => {
    document.getElementById('screen-comparison-mode').textContent = input.value === 'MANUAL' ? 'Manual' : 'Automática';
  }));
  document.querySelectorAll('input[name="depth"]').forEach(input => input.addEventListener('change', () => {
    if (input.checked) document.getElementById('screen-depth-mode').textContent = input.value === 'DEEP' ? 'Ampliada' : 'Rápida';
  }));

  const originalSetWorkflowStep = window.setWorkflowStep;
  window.setWorkflowStep = function (step) {
    originalSetWorkflowStep(step);
    if (step === 1) showScreen('home', {preserveScroll: true, instant: true});
    if (step > 1) {
      analysisAvailable = true;
      analysisNav.hidden = false;
    }
  };

  const originalSetInputMode = window.setInputMode;
  window.setInputMode = function (mode, focus) {
    homeEntry = mode;
    originalSetInputMode(mode, focus);
    if (activeScreen === 'home') updateNav('home');
  };

  const originalSetProgress = window.setProgress;
  window.setProgress = function (status, progressValue) {
    originalSetProgress(status, progressValue);
    if (['QUEUED', 'RUNNING', 'RESEARCHING', 'FAILED'].includes(status)) showScreen('processing', {preserveScroll: activeScreen === 'processing', instant: true, force: true});
    if (status === 'AWAITING_CLAIM_SELECTION') {
      analysisAvailable = true;
      claimsAvailable = true;
      showScreen('reading', {instant: true});
    }
    if (status === 'SUCCEEDED') {
      analysisAvailable = true;
      claimsAvailable = true;
      resultsAvailable = true;
      showScreen('results', {instant: true});
    }
  };

  function installSlidingIndicator(container, itemSelector, className, rail = false) {
    const indicator = document.createElement('span');
    indicator.className = className;
    indicator.setAttribute('aria-hidden', 'true');
    container.prepend(indicator);
    const update = () => {
      const item = container.querySelector(`${itemSelector}.is-active`);
      if (!item) return;
      const mobileRail = rail && matchMedia('(max-width: 760px)').matches;
      const left = mobileRail ? item.offsetLeft + 8 : rail ? 0 : item.offsetLeft;
      const top = mobileRail ? 0 : rail ? item.offsetTop + 8 : item.offsetTop;
      const width = mobileRail ? Math.max(8, item.offsetWidth - 16) : rail ? 3 : item.offsetWidth;
      const height = mobileRail ? 2 : rail ? Math.max(8, item.offsetHeight - 16) : item.offsetHeight;
      indicator.style.left = `${left}px`;
      indicator.style.top = `${top}px`;
      indicator.style.width = `${width}px`;
      indicator.style.height = `${height}px`;
    };
    const observer = new MutationObserver(() => requestAnimationFrame(update));
    container.querySelectorAll(itemSelector).forEach(item => observer.observe(item, {attributes: true, attributeFilter: ['class']}));
    new ResizeObserver(update).observe(container);
    requestAnimationFrame(update);
    return update;
  }

  const updateSidebarIndicator = installSlidingIndicator(document.querySelector('.side-nav'), '.nav-item', 'nav-spotlight', true);
  const updateEntryIndicator = installSlidingIndicator(document.querySelector('.entry-tabs'), '.entry-tab', 'entry-tab-indicator');
  const updateResultIndicator = installSlidingIndicator(resultNav, 'button', 'result-tab-indicator');

  [document.getElementById('topic-submit'), document.getElementById('submit'), document.getElementById('research-selected'), reviewButton]
    .filter(Boolean).forEach(button => button.classList.add('vault-action'));

  function syncClaimChecklist() {
    document.querySelectorAll('#review-claims .review-claim').forEach(card => {
      card.classList.toggle('is-selected', Boolean(card.querySelector('input[type="checkbox"]')?.checked));
    });
  }
  document.getElementById('review-claims').addEventListener('change', event => {
    if (event.target.matches('input[type="checkbox"]')) syncClaimChecklist();
  });
  new MutationObserver(syncClaimChecklist).observe(document.getElementById('review-claims'), {childList: true, subtree: true});
  document.getElementById('watch-toggle').addEventListener('change', event => {
    event.target.closest('.watch-toggle')?.classList.toggle('is-enabled', event.target.checked);
  });

  const countObserver = new MutationObserver(() => {
    const count = document.getElementById('library-count').textContent.match(/\d+/)?.[0] || '0';
    document.getElementById('library-total-stat').textContent = count;
  });
  countObserver.observe(document.getElementById('library-count'), {childList: true, characterData: true, subtree: true});

  main.insertBefore(topbar, home);
  main.append(preview, footer);
  const initialHash = Object.entries(screenHashes).find(([, hash]) => location.hash === `#${hash}`)?.[0];
  showScreen(initialHash === 'library' ? 'library' : 'home', {instant: true, force: true, preserveHash: Boolean(initialHash)});
  addEventListener('hashchange', () => {
    const target = Object.entries(screenHashes).find(([, hash]) => location.hash === `#${hash}`)?.[0];
    if (target && canOpen(target)) showScreen(target, {instant: true, preserveHash: true});
  });
  addEventListener('resize', () => { updateSidebarIndicator(); updateEntryIndicator(); updateResultIndicator(); });
  window.appScreens = {show: showScreen, current: () => activeScreen};
})();
