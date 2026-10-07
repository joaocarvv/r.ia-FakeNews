/* Navegação da área de pesquisa. Os contratos da análise permanecem na página. */
if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
window.scrollTo({top: 0, left: 0});
function setInputMode(mode, focus = false) {
  if (!['search', 'link', 'upload'].includes(mode)) return;
  if (document.body.classList.contains('has-analysis')) {
    setWorkflowStep(1);
    ['whole-article-report', 'claim-review', 'result'].forEach(id => { document.getElementById(id).style.display = 'none'; });
  }
  document.querySelectorAll('.entry-tab').forEach(tab => {
    const active = tab.dataset.entry === mode;
    tab.classList.toggle('is-active', active);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll('.side-nav [data-entry]').forEach(item => {
    item.classList.toggle('is-active', item.dataset.entry === (mode === 'search' ? 'search' : 'link'));
  });
  document.getElementById('topic-workspace').hidden = mode !== 'search';
  const articlePanel = document.getElementById('article-workspace');
  articlePanel.hidden = mode === 'search';
  articlePanel.setAttribute('aria-labelledby', mode === 'upload' ? 'tab-upload' : 'tab-link');
  document.getElementById('link-field').hidden = mode !== 'link';
  document.getElementById('upload-field').hidden = mode !== 'upload';
  document.getElementById('article-entry-description').textContent = mode === 'upload'
    ? 'Envie o documento que você quer ler. Os trechos de origem acompanham a análise.'
    : 'Cole um link do PubMed, PMID ou DOI para começar a leitura.';
  if (mode === 'link') {
    document.getElementById('article-file').value = '';
    updateUpload();
  }
  if (mode === 'upload') document.getElementById('article-reference').value = '';
  if (focus) {
    document.getElementById(mode === 'search' ? 'topic-input' : mode === 'link' ? 'article-reference' : 'article-file').focus({preventScroll: true});
  }
}

function setWorkflowStep(step) {
  if (step === 1) {
    document.getElementById('source-reader').hidden = true;
    if (typeof closeClaimPopover === 'function') closeClaimPopover();
  }
  document.body.classList.toggle('has-analysis', step > 1);
  document.querySelector('.entry-workspace').hidden = step > 1;
  document.querySelector('.safety-note').hidden = step > 1;
  document.getElementById('change-source').hidden = step === 1;
  const heading = document.querySelector('.workspace-header h1');
  heading.replaceChildren();
  heading.append(document.createTextNode(step === 1 ? 'Uma leitura mais clara.' : step === 2 ? 'Seu artigo, organizado.' : 'Evidências para conferir.'));
  if (step === 1) {
    heading.appendChild(document.createElement('br'));
    const secondLine = document.createElement('span'); secondLine.textContent = 'Com as fontes à vista.';
    heading.appendChild(secondLine);
  }
  document.querySelector('.workspace-header .subtitle').textContent = step === 1
    ? 'Encontre estudos sobre um tema ou traga um artigo. Organize a leitura e compare os trechos com outras pesquisas.'
    : step === 2 ? 'Leia o resumo, confira os trechos de origem e escolha o que deseja investigar.'
    : 'Comece pelo resumo e confira os estudos que fundamentam a comparação.';
  document.querySelectorAll('.workflow li').forEach(item => {
    const current = Number(item.dataset.step) === step;
    item.classList.toggle('is-current', current);
    item.classList.toggle('is-done', Number(item.dataset.step) < step);
    if (current) item.setAttribute('aria-current', 'step');
    else item.removeAttribute('aria-current');
  });
}

document.getElementById('change-source').addEventListener('click', () => {
  setInputMode('search', true);
  document.getElementById('workspace').scrollIntoView({behavior: 'smooth', block: 'start'});
});

function updateUpload() {
  const file = document.getElementById('article-file').files[0];
  const zone = document.getElementById('upload-zone');
  zone.classList.toggle('has-file', Boolean(file));
  document.getElementById('upload-name').textContent = file ? `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MB` : '';
  zone.querySelector('strong').textContent = file ? 'Arquivo pronto para leitura' : 'Solte seu artigo aqui';
}

function disclose(node, title) {
  if (!node) return;
  const details = document.createElement('details');
  details.className = 'panel section-disclosure';
  const summary = document.createElement('summary'); summary.textContent = title;
  const content = document.createElement('div'); content.className = 'disclosure-content';
  node.before(details); content.appendChild(node); details.append(summary, content);
}

document.querySelectorAll('[data-entry]').forEach(button => {
  button.addEventListener('click', () => setInputMode(button.dataset.entry));
});
document.querySelectorAll('.entry-tab').forEach((tab, index, tabs) => {
  tab.addEventListener('keydown', event => {
    let target;
    if (event.key === 'ArrowRight') target = tabs[(index + 1) % tabs.length];
    if (event.key === 'ArrowLeft') target = tabs[(index - 1 + tabs.length) % tabs.length];
    if (event.key === 'Home') target = tabs[0];
    if (event.key === 'End') target = tabs[tabs.length - 1];
    if (target) { event.preventDefault(); setInputMode(target.dataset.entry); target.focus(); }
  });
});
document.querySelectorAll('[data-topic]').forEach(button => {
  button.addEventListener('click', () => {
    document.getElementById('topic-input').value = button.dataset.topic;
    document.getElementById('topic-input').focus();
  });
});
const uploadZone = document.getElementById('upload-zone');
document.getElementById('article-file').addEventListener('change', updateUpload);
uploadZone.addEventListener('dragover', event => { event.preventDefault(); uploadZone.classList.add('is-dragging'); });
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('is-dragging'));
uploadZone.addEventListener('drop', event => {
  event.preventDefault(); uploadZone.classList.remove('is-dragging');
  const file = event.dataTransfer.files[0];
  if (!file) return;
  const allowed = ['application/pdf', 'image/png', 'image/jpeg', 'image/webp'];
  if (!allowed.includes(file.type) || file.size > 25 * 1024 * 1024) {
    document.getElementById('upload-name').textContent = 'Escolha um PDF, PNG, JPEG ou WebP com até 25 MB.';
    return;
  }
  const transfer = new DataTransfer(); transfer.items.add(file);
  document.getElementById('article-file').files = transfer.files;
  updateUpload();
});

// Sequência da resposta: resumo, balanço, trechos, limites e tabela.
const result = document.getElementById('result');
const indicators = result.querySelector('.indicator-grid');
const overview = result.querySelector('.result-grid');
const balance = document.getElementById('weighted-title').closest('section');
const findings = document.getElementById('findings').closest('.panel');
const limits = document.getElementById('limitations').closest('.result-grid');
const table = document.getElementById('table-title').closest('section');
result.insertBefore(overview, indicators);
overview.after(balance); balance.after(findings); findings.after(limits); limits.after(table);
disclose(indicators, 'Cobertura da busca e limites metodológicos');
disclose(document.getElementById('map-title').closest('section'), 'Linha do tempo dos estudos');
disclose(document.getElementById('updates-title').closest('section'), 'Acompanhar novos estudos');
disclose(document.getElementById('crossing-title').closest('section'), 'Consultas, fontes e etapas da pesquisa');
document.querySelectorAll('#whole-article-report .report-columns').forEach((node, index) => {
  disclose(node, index === 0 ? 'Resultados e limitações declaradas' : 'Tabelas, financiamento e conflitos de interesse');
});
disclose(document.getElementById('whole-study'), 'Características relatadas no texto');

const guide = document.createElement('dialog');
guide.className = 'guide-dialog'; guide.setAttribute('aria-labelledby', 'guide-title');
const guideTitle = document.createElement('h2'); guideTitle.id = 'guide-title'; guideTitle.textContent = 'Como funciona a leitura';
const guideText = document.createElement('p'); guideText.textContent = 'Pesquise um tema no PubMed ou traga seu artigo. Depois da leitura, confira as afirmações extraídas e escolha quais quer comparar.';
const guideLimits = document.createElement('p'); guideLimits.textContent = 'As evidências aparecem com trechos e fontes. Quando o texto completo não está disponível no PMC, a análise usa o resumo e informa essa limitação. A qualidade metodológica exige avaliação especializada.';
const closeGuide = document.createElement('button'); closeGuide.type = 'button'; closeGuide.textContent = 'Entendi'; closeGuide.addEventListener('click', () => guide.close());
guide.append(guideTitle, guideText, guideLimits, closeGuide); document.body.appendChild(guide);
document.getElementById('guide-open').addEventListener('click', () => guide.showModal());
guide.addEventListener('click', event => { if (event.target === guide) { const box = guide.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) guide.close(); } });
