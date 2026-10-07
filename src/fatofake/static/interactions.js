/* Original SVGs and interactions; no third-party runtime or remote assets. */
(() => {
  const paths = {
    search: ['M21 21l-5-5', 'M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0'],
    article: ['M6 3h9l4 4v14H6z', 'M14 3v5h5', 'M9 12h7M9 16h5'],
    library: ['M4 4h4v16H4zM10 4h4v16h-4z', 'M16 5l3-1 4 15-3 1z'],
    info: ['M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0', 'M12 11v6M12 7h.01'],
    upload: ['M12 16V3M7 8l5-5 5 5', 'M4 15v6h16v-6'],
    check: ['M5 12l4 4L19 6'],
    copy: ['M9 9h11v12H9z', 'M15 9V3H3v12h6']
  };
  function icon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false'); svg.classList.add('ui-icon');
    paths[name].forEach(d => {
      const path = document.createElementNS(svg.namespaceURI, 'path'); path.setAttribute('d', d); svg.append(path);
    });
    return svg;
  }
  const targets = [
    ['.side-nav [data-entry="search"] > span', 'search'],
    ['.side-nav [data-entry="link"] > span', 'article'],
    ['#library-open > span', 'library'], ['#guide-open > span', 'info']
  ];
  targets.forEach(([selector, name]) => document.querySelector(selector).replaceChildren(icon(name)));
  document.querySelectorAll('.entry-tab').forEach(tab => tab.prepend(icon(({search:'search', link:'article', upload:'upload'})[tab.dataset.entry])));
  const tablist = document.querySelector('.entry-tabs');
  const indicator = document.createElement('span'); indicator.className = 'entry-tab-indicator';
  indicator.setAttribute('aria-hidden', 'true'); tablist.append(indicator);
  function moveIndicator() {
    const active = tablist.querySelector('[aria-selected="true"]');
    indicator.style.width = `${active.offsetWidth}px`; indicator.style.height = `${active.offsetHeight}px`;
    indicator.style.transform = `translate(${active.offsetLeft}px, ${active.offsetTop}px)`;
    tablist.classList.add('has-indicator');
  }
  moveIndicator();
  new MutationObserver(moveIndicator).observe(tablist, {subtree:true, attributes:true, attributeFilter:['aria-selected']});
  new ResizeObserver(moveIndicator).observe(tablist);
  const upload = document.getElementById('upload-zone');
  const paintUpload = () => upload.querySelector('.upload-icon').replaceChildren(icon(upload.classList.contains('has-file') ? 'check' : 'upload'));
  paintUpload();
  new MutationObserver(paintUpload).observe(upload, {attributes:true, attributeFilter:['class']});

  document.getElementById('library-open').addEventListener('click', event => {
    event.preventDefault();
    const library = document.getElementById('article-library');
    library.scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block:'start'});
    library.focus({preventScroll:true});
  });
  const toast = document.createElement('div'); toast.className = 'ui-toast'; toast.hidden = true;
  toast.setAttribute('role', 'status'); toast.setAttribute('aria-live', 'polite'); document.body.append(toast);
  let toastTimer;
  function notify(text) {
    clearTimeout(toastTimer); toast.textContent = text; toast.hidden = false;
    toastTimer = setTimeout(() => { toast.hidden = true; }, 4000);
  }
  const findings = document.getElementById('findings');
  new MutationObserver(() => {
    findings.querySelectorAll('.copy-evidence:not([data-icon-ready])').forEach(button => {
      button.dataset.iconReady = 'true'; button.prepend(icon('copy'));
    });
  }).observe(findings, {childList:true, subtree:true});
  findings.addEventListener('click', async event => {
    const button = event.target.closest('.copy-evidence');
    if (!button || button.disabled) return;
    button.disabled = true;
    try {
      await navigator.clipboard.writeText(button.dataset.copyText);
      button.replaceChildren(icon('check'), document.createTextNode('Trecho copiado'));
      button.classList.add('is-copied'); notify('Trecho original e referência copiados.');
      setTimeout(() => {
        button.replaceChildren(icon('copy'), document.createTextNode('Copiar trecho e fonte'));
        button.classList.remove('is-copied'); button.disabled = false;
      }, 1800);
    } catch {
      button.disabled = false;
      notify('Não foi possível acessar a área de transferência. Selecione o trecho para copiá-lo.');
    }
  });
})();
