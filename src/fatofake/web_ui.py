"""Interface web mínima para testes de aceitação do fluxo científico."""

from __future__ import annotations

from html import escape

from flask import Flask, Response


WEB_UI_HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Fato ou Fake? — Evidências em saúde</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #17221d;
      --muted: #5d6a64;
      --paper: #f6f3eb;
      --surface: #fffdf8;
      --line: #d8ddd7;
      --brand: #145a45;
      --brand-dark: #0e4032;
      --accent: #e7a84b;
      --danger: #9b3d31;
      --shadow: 0 18px 55px rgba(30, 52, 43, .11);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background:
        radial-gradient(circle at 8% 6%, rgba(231, 168, 75, .20), transparent 25rem),
        linear-gradient(145deg, #f4f0e5 0%, #f7f8f3 55%, #edf3ee 100%);
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.55;
    }
    .shell { width: min(1080px, calc(100% - 32px)); margin: 0 auto; padding: 34px 0 64px; }
    header { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; margin-bottom: 24px; }
    .eyebrow { color: var(--brand); font-size: .78rem; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
    h1 { margin: 6px 0 4px; font-family: Georgia, 'Times New Roman', serif; font-size: clamp(2.2rem, 6vw, 4.4rem); line-height: .96; letter-spacing: -.045em; }
    .subtitle { margin: 12px 0 0; max-width: 690px; color: var(--muted); font-size: 1.06rem; }
    .mode {
      flex: 0 0 auto; max-width: 310px; padding: 12px 14px; border: 1px solid #d69a43;
      border-radius: 12px; background: #fff5df; color: #684313; font-size: .82rem; font-weight: 700;
    }
    .panel { border: 1px solid rgba(20, 90, 69, .18); border-radius: 20px; background: rgba(255, 253, 248, .94); box-shadow: var(--shadow); }
    .form-panel { padding: clamp(20px, 4vw, 36px); }
    label { display: block; margin-bottom: 8px; font-weight: 750; }
    textarea, input {
      width: 100%; border: 1px solid #bfc9c1; border-radius: 12px; background: #fff;
      padding: 14px 15px; color: var(--ink); font: inherit; outline: none;
    }
    textarea { min-height: 118px; resize: vertical; }
    textarea:focus, input:focus { border-color: var(--brand); box-shadow: 0 0 0 3px rgba(20, 90, 69, .12); }
    .field + .field { margin-top: 18px; }
    .hint { margin: 6px 0 0; color: var(--muted); font-size: .83rem; }
    .actions { display: flex; align-items: center; gap: 16px; margin-top: 22px; flex-wrap: wrap; }
    button {
      border: 0; border-radius: 999px; padding: 13px 22px; background: var(--brand); color: white;
      font: inherit; font-weight: 800; cursor: pointer; transition: transform .15s ease, background .15s ease;
    }
    button:hover { background: var(--brand-dark); transform: translateY(-1px); }
    button:disabled { opacity: .55; cursor: wait; transform: none; }
    .safety { color: var(--muted); font-size: .83rem; max-width: 560px; }
    #status { display: none; margin-top: 22px; padding: 16px; border-radius: 13px; background: #eef5f0; }
    .status-row { display: flex; justify-content: space-between; gap: 12px; font-size: .9rem; font-weight: 700; }
    .progress { height: 8px; margin-top: 10px; overflow: hidden; border-radius: 99px; background: #dbe5df; }
    .progress > div { height: 100%; width: 0; background: var(--brand); transition: width .25s ease; }
    #error { display: none; margin-top: 20px; padding: 15px 17px; border: 1px solid #e2b3ad; border-radius: 12px; background: #fff0ee; color: var(--danger); }
    #result { display: none; margin-top: 28px; }
    .result-grid { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(260px, .6fr); gap: 20px; }
    .result-card { padding: 24px; }
    .kicker { color: var(--brand); font-size: .75rem; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }
    h2 { margin: 7px 0 10px; font-family: Georgia, 'Times New Roman', serif; font-size: 2rem; line-height: 1.08; }
    h3 { margin: 0 0 14px; font-size: 1.05rem; }
    .indicator-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 0 0 20px; }
    .indicator-card { padding: 19px; }
    .indicator-card h3 { margin: 7px 0 8px; }
    .indicator-card p { margin: 0; color: var(--muted); font-size: .87rem; }
    .indicator-note { grid-column: 1 / -1; margin: -4px 2px 0; color: var(--muted); font-size: .8rem; }
    .stack { display: grid; gap: 16px; margin-top: 20px; }
    .alert-list { display: grid; gap: 10px; padding: 0; list-style: none; }
    .alert-item { padding: 12px 14px; border-left: 4px solid var(--accent); border-radius: 8px; background: #fff8e9; }
    .alert-item[data-severity="CRITICAL"] { border-color: var(--danger); background: #fff0ee; }
    .alert-item strong { display: block; }
    .article-meta { color: var(--muted); font-size: .82rem; }
    .evidence { margin-top: 13px; padding-left: 13px; border-left: 3px solid var(--accent); }
    .evidence p { margin: 4px 0; }
    .badge { display: inline-block; padding: 3px 8px; border-radius: 999px; background: #e7f0eb; color: var(--brand-dark); font-size: .72rem; font-weight: 800; }
    .summary-box { margin-top: 18px; padding: 16px; border-radius: 13px; background: #eef5f0; }
    .summary-box strong { display: block; margin-bottom: 5px; }
    .claim-navigation { margin-bottom: 20px; padding: 20px 24px; }
    .claim-navigation p { margin: -6px 0 14px; color: var(--muted); font-size: .88rem; }
    .claim-tabs { display: grid; gap: 9px; }
    .claim-tab {
      width: 100%; border: 1px solid var(--line); border-radius: 12px; padding: 11px 14px;
      background: #fbfcf9; color: var(--ink); font-weight: 650; text-align: left;
    }
    .claim-tab:hover { border-color: var(--brand); background: #eef5f0; color: var(--brand-dark); }
    .claim-tab[aria-selected="true"] { border-color: var(--brand); background: var(--brand); color: white; }
    .finding { padding: 20px; border: 1px solid var(--line); border-radius: 12px; background: #fbfcf9; }
    .finding[data-relation="CONTRADICTS"] { border-left: 5px solid var(--danger); }
    .finding[data-relation="SUPPORTS"] { border-left: 5px solid var(--brand); }
    .finding[data-relation="NEUTRAL"], .finding[data-relation="UNCERTAIN"] { border-left: 5px solid var(--accent); }
    .finding blockquote { margin: 12px 0; padding-left: 14px; border-left: 3px solid var(--line); color: #304039; }
    details { margin-top: 20px; }
    summary { cursor: pointer; color: var(--brand); font-weight: 750; }
    ul { margin: 0; padding-left: 20px; }
    li + li { margin-top: 8px; }
    a { color: var(--brand); overflow-wrap: anywhere; }
    footer { margin-top: 28px; color: var(--muted); font-size: .79rem; text-align: center; }
    @media (max-width: 760px) {
      header { display: block; }
      .mode { margin-top: 18px; max-width: none; }
      .result-grid { grid-template-columns: 1fr; }
      .indicator-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div>
        <div class="eyebrow">Residência em Inteligência Artificial</div>
        <h1>Fato ou Fake?</h1>
        <p class="subtitle">Envie um artigo e compare suas principais alegações com literatura científica independente — com fontes, limites e incertezas visíveis.</p>
      </div>
      <div class="mode">__MODE_LABEL__</div>
    </header>

    <section class="panel form-panel" aria-labelledby="form-title">
      <h2 id="form-title">Qual artigo você quer verificar?</h2>
      <form id="analysis-form">
        <div class="field">
          <label for="article-reference">Link ou DOI do artigo</label>
          <input id="article-reference" maxlength="500" placeholder="https://pubmed.ncbi.nlm.nih.gov/... ou 10.xxxx/...">
          <p class="hint">Informe um link/DOI ou escolha um arquivo abaixo — não os dois.</p>
        </div>
        <div class="field">
          <label for="article-file">Imagem ou arquivo do artigo</label>
          <input id="article-file" type="file" accept="application/pdf,image/png,image/jpeg,image/webp">
          <p class="hint">Formatos aceitos: PDF, PNG, JPEG e WebP, com até 10 MB.</p>
        </div>
        <div class="actions">
          <button id="submit" type="submit">Verificar artigo</button>
          <div class="safety">A ferramenta não oferece diagnóstico nem substitui profissionais de saúde. Ela pode errar e deve manter as fontes disponíveis para conferência.</div>
        </div>
      </form>
      <div id="status" role="status" aria-live="polite">
        <div class="status-row"><span id="status-text">Preparando análise…</span><span id="progress-text">0%</span></div>
        <div class="progress" aria-hidden="true"><div id="progress-bar"></div></div>
      </div>
      <div id="error" role="alert"></div>
    </section>

    <section id="result" aria-live="polite">
      <section id="claim-navigation" class="panel claim-navigation" aria-labelledby="claims-title">
        <h3 id="claims-title">Alegações identificadas no artigo</h3>
        <p>Cada alegação possui busca, evidências e resultado próprios. Selecione uma para conferir.</p>
        <div id="claim-tabs" class="claim-tabs" role="tablist"></div>
      </section>
      <section class="indicator-grid" aria-label="Indicadores separados da análise">
        <article class="panel indicator-card">
          <div class="kicker">Cobertura da busca</div>
          <h3 id="coverage-label"></h3>
          <p id="coverage-detail"></p>
        </article>
        <article class="panel indicator-card">
          <div class="kicker">Compatibilidade das evidências</div>
          <h3 id="compatibility-label"></h3>
          <p id="compatibility-detail"></p>
        </article>
        <article class="panel indicator-card">
          <div class="kicker">Confiança metodológica</div>
          <h3 id="methodology-label"></h3>
          <p id="methodology-detail"></p>
        </article>
        <p class="indicator-note">Os três indicadores têm significados diferentes e não representam uma probabilidade de o artigo estar correto.</p>
      </section>
      <div class="result-grid">
        <article class="panel result-card">
          <div class="kicker">Resposta em linguagem clara</div>
          <p id="extracted-claim" class="evidence"></p>
          <p id="claim-quote" class="evidence"></p>
          <h2 id="headline"></h2>
          <p id="summary"></p>
          <div class="summary-box">
            <strong>Como interpretar</strong>
            <span id="interpretation"></span>
          </div>
        </article>
        <aside class="panel result-card">
          <h3>O que conseguimos ler</h3>
          <p id="reading-summary"></p>
          <h3>Próximo passo recomendado</h3>
          <p id="next-action"></p>
        </aside>
      </div>
      <details id="article-dossier" class="panel result-card">
        <summary>Ver ficha do artigo enviado</summary>
        <div class="stack" id="dossier-items"></div>
      </details>
      <div class="panel result-card" style="margin-top: 20px">
        <div class="kicker">Trechos que sustentam a comparação</div>
        <h3>Evidências independentes encontradas</h3>
        <div class="stack" id="findings"></div>
      </div>
      <div class="result-grid" style="margin-top: 20px">
        <article class="panel result-card">
          <h3>Limitações desta análise</h3>
          <ul id="limitations"></ul>
        </article>
        <aside class="panel result-card">
          <h3>Fontes para conferência manual</h3>
          <ul id="sources"></ul>
        </aside>
      </div>
      <details class="panel result-card">
        <summary>Ver detalhes técnicos e alertas</summary>
        <p id="technical-coverage"></p>
        <ul id="verification-alerts" class="alert-list"></ul>
      </details>
    </section>

    <footer>Protótipo acadêmico. O sistema avalia compatibilidade com o corpus recuperado, não uma verdade médica absoluta.</footer>
  </main>
  <script>
    const form = document.getElementById('analysis-form');
    const submit = document.getElementById('submit');
    const statusBox = document.getElementById('status');
    const statusText = document.getElementById('status-text');
    const progressText = document.getElementById('progress-text');
    const progressBar = document.getElementById('progress-bar');
    const errorBox = document.getElementById('error');
    const resultBox = document.getElementById('result');

    const text = value => value == null ? 'Não informado' : String(value);
    const safeUrl = value => {
      try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; }
      catch (_) { return null; }
    };
    function clearNode(node) { while (node.firstChild) node.removeChild(node.firstChild); }
    function addTextElement(parent, tag, value, className) {
      const element = document.createElement(tag); element.textContent = text(value);
      if (className) element.className = className; parent.appendChild(element); return element;
    }
    function showError(message) {
      errorBox.textContent = message; errorBox.style.display = 'block';
      statusBox.style.display = 'none'; submit.disabled = false;
    }
    function setProgress(status, progress) {
      const names = {QUEUED: 'Análise na fila…', RUNNING: 'Consultando e comparando evidências…'};
      statusText.textContent = names[status] || 'Preparando resultado…';
      progressText.textContent = `${progress}%`; progressBar.style.width = `${progress}%`;
    }
    function renderResult(data, shouldScroll) {
      const report = data.report || {};
      const verification = data.verification || {};
      const submitted = data.submitted_article || {};
      const narrative = data.user_summary || {
        headline: report.headline,
        summary: report.summary,
        claim: submitted.primary_claim,
        interpretation: 'A saída técnica não trouxe um resumo consolidado.',
        reading: {}, evidence_balance: {}, findings: [],
        caveats: report.limitations || [], next_action: 'Confira as fontes manualmente.'
      };
      const extractedClaim = document.getElementById('extracted-claim');
      extractedClaim.textContent = narrative.claim ? `O artigo afirma: ${narrative.claim}` : '';
      extractedClaim.style.display = narrative.claim ? 'block' : 'none';
      const claimQuote = document.getElementById('claim-quote');
      const submittedLocation = submitted.primary_claim_section
        ? ` — seção ${submitted.primary_claim_section}${submitted.primary_claim_page ? `, página ${submitted.primary_claim_page}` : ' (fonte sem paginação)'}`
        : (submitted.primary_claim_page ? ` — página ${submitted.primary_claim_page}` : '');
      claimQuote.textContent = submitted.primary_claim_quote ? `Trecho original: “${submitted.primary_claim_quote}”${submittedLocation}` : '';
      claimQuote.style.display = submitted.primary_claim_quote ? 'block' : 'none';
      document.getElementById('headline').textContent = text(narrative.headline);
      document.getElementById('summary').textContent = text(narrative.summary);
      document.getElementById('interpretation').textContent = text(narrative.interpretation);
      document.getElementById('next-action').textContent = text(narrative.next_action);

      const reading = narrative.reading || {};
      document.getElementById('reading-summary').textContent = text(reading.summary);

      const indicators = verification.indicators || {};
      const coverage = indicators.search_coverage || {};
      const compatibility = indicators.evidence_compatibility || {};
      const methodology = indicators.methodological_confidence || {};
      document.getElementById('coverage-label').textContent = text(coverage.label);
      document.getElementById('coverage-detail').textContent = text(coverage.explanation);
      document.getElementById('compatibility-label').textContent = text(compatibility.label);
      document.getElementById('compatibility-detail').textContent = text(compatibility.explanation);
      document.getElementById('methodology-label').textContent = text(methodology.label);
      document.getElementById('methodology-detail').textContent = text(methodology.explanation);

      const dossier = data.article_dossier || {};
      const dossierPanel = document.getElementById('article-dossier');
      const dossierItems = document.getElementById('dossier-items'); clearNode(dossierItems);
      dossierPanel.style.display = Object.keys(dossier).length ? 'block' : 'none';
      if (Object.keys(dossier).length) {
        const identity = dossier.identity || {};
        const publication = dossier.publication || {};
        const editorial = dossier.editorial_status || {};
        const dossierMethod = dossier.methodology || {};
        const transparency = dossier.transparency || {};
        const sample = dossierMethod.sample_size || {};
        const protocol = dossierMethod.protocol || {};
        const addDossierItem = (title, detail) => {
          const card = document.createElement('article'); card.className = 'finding';
          addTextElement(card, 'h3', title); addTextElement(card, 'p', detail); dossierItems.appendChild(card);
        };
        addDossierItem('Identidade e publicação',
          `${identity.explanation || 'Identidade não confirmada'} Autores: ${identity.authors_consistency || 'UNKNOWN'}. ` +
          `DOI: ${identity.doi || 'não informado'}; periódico: ${publication.journal || 'não informado'}; data: ${publication.publication_date || 'não informada'}.`);
        addDossierItem('Status editorial',
          `Revisão por pares: ${editorial.peer_review || 'UNKNOWN'}. Retratação: ${editorial.retraction || 'UNKNOWN'}. ` +
          `${editorial.retraction_explanation || ''}`);
        addDossierItem('Desenho, amostra e protocolo',
          `Desenho: ${dossierMethod.study_design || 'UNKNOWN'}; fonte: ${dossierMethod.classification_source || 'UNRESOLVED'}. ` +
          `Amostra: ${sample.value == null ? 'não localizada' : sample.value}. Protocolos: ${(protocol.identifiers || []).join(', ') || 'não localizados'}.`);
        addDossierItem('Transparência',
          `Financiamento: ${transparency.funding?.status || 'UNKNOWN'}. Conflitos de interesse: ${transparency.conflicts_of_interest?.status || 'UNKNOWN'}. ` +
          `Disponibilidade de dados: ${transparency.data_availability?.status || 'UNKNOWN'}.`);
        addDossierItem('Limites da ficha',
          `${dossier.results_conclusion_consistency?.explanation || 'Consistência entre resultados e conclusão não avaliada.'}`);
      }

      const limitations = document.getElementById('limitations'); clearNode(limitations);
      (narrative.caveats || []).forEach(item => addTextElement(limitations, 'li', item));

      const partial = verification.partial_verification || {};
      const meta = verification.meta_analysis || {};
      const trials = verification.clinical_trials || {};
      const search = data.search || {};
      const reranking = search.reranking || {};
      const technicalParts = [
        `Processamento detalhado: ${partial.verified_count || 0} de ${partial.total_count || 0} documentos com evidência utilizável.`,
        `Busca ampliada: ${(search.query_expansion || []).length} estratégias; reranker manteve ${reranking.accepted_count || 0} de ${reranking.evaluated_count || 0} candidatos.`,
        `Meta-análises: ${text(meta.explanation)}.`,
        `Ensaios clínicos: ${text(trials.explanation)}.`
      ];
      document.getElementById('technical-coverage').textContent = technicalParts.join(' ');

      const alerts = document.getElementById('verification-alerts'); clearNode(alerts);
      const alertItems = verification.alerts || [];
      if (!alertItems.length) addTextElement(alerts, 'li', 'Nenhum alerta automático foi produzido.');
      alertItems.forEach(item => {
        const li = document.createElement('li'); li.className = 'alert-item';
        li.dataset.severity = item.severity || 'INFO';
        addTextElement(li, 'strong', item.title);
        addTextElement(li, 'span', item.detail);
        const url = safeUrl(item.source_url);
        if (url) { const link = document.createElement('a'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = ' Conferir fonte'; li.appendChild(link); }
        alerts.appendChild(li);
      });

      const findings = document.getElementById('findings'); clearNode(findings);
      if (!(narrative.findings || []).length) {
        addTextElement(findings, 'p', 'Nenhum trecho independente pôde ser citado com segurança nesta execução.');
      }
      (narrative.findings || []).forEach(item => {
        const card = document.createElement('article'); card.className = 'finding';
        card.dataset.relation = item.relation || 'UNCERTAIN';
        addTextElement(card, 'span', item.relation_label, 'badge');
        addTextElement(card, 'h3', item.article_title);
        addTextElement(card, 'div', `${item.publication_date || 'data não informada'} · ${item.scope_label}`, 'article-meta');
        if (item.quote) addTextElement(card, 'blockquote', `“${item.quote}”`);
        addTextElement(card, 'div', item.location, 'article-meta');
        const url = safeUrl(item.source_url);
        if (url) { const link = document.createElement('a'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = 'Conferir no artigo'; card.appendChild(link); }
        findings.appendChild(card);
      });

      const sources = document.getElementById('sources'); clearNode(sources);
      (report.sources || []).forEach(source => {
        const li = document.createElement('li'); const url = safeUrl(source.url);
        if (url) { const link = document.createElement('a'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = text(source.label); li.appendChild(link); }
        else { li.textContent = text(source.label); }
        sources.appendChild(li);
      });
      statusBox.style.display = 'none'; resultBox.style.display = 'block'; submit.disabled = false;
      if (shouldScroll !== false) resultBox.scrollIntoView({behavior: 'smooth', block: 'start'});
    }
    function renderAnalysis(data) {
      const navigation = document.getElementById('claim-navigation');
      const tabs = document.getElementById('claim-tabs'); clearNode(tabs);
      const analyses = (data.claim_analyses || []).filter(item => item.status === 'SUCCEEDED' && item.result);
      if (!analyses.length) {
        navigation.style.display = 'none';
        renderResult(data, true);
        return;
      }
      navigation.style.display = 'block';
      analyses.forEach((analysis, index) => {
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'claim-tab'; button.setAttribute('role', 'tab');
        button.setAttribute('aria-selected', index === 0 ? 'true' : 'false');
        button.textContent = `${index + 1}. ${analysis.claim?.text || analysis.claim_id}`;
        button.addEventListener('click', () => {
          tabs.querySelectorAll('.claim-tab').forEach(item => item.setAttribute('aria-selected', 'false'));
          button.setAttribute('aria-selected', 'true');
          renderResult(analysis.result, false);
        });
        tabs.appendChild(button);
      });
      renderResult(analyses[0].result, true);
    }
    async function poll(statusUrl) {
      for (;;) {
        const response = await fetch(statusUrl, {headers: {'Accept': 'application/json'}});
        if (!response.ok) throw new Error('Não foi possível consultar o andamento da análise.');
        const job = await response.json(); setProgress(job.status, job.progress || 0);
        if (job.status === 'SUCCEEDED') { renderAnalysis(job.result); return; }
        if (job.status === 'FAILED') throw new Error(job.error?.message || 'A análise falhou.');
        await new Promise(resolve => setTimeout(resolve, 700));
      }
    }
    form.addEventListener('submit', async event => {
      event.preventDefault(); submit.disabled = true; errorBox.style.display = 'none';
      resultBox.style.display = 'none'; statusBox.style.display = 'block'; setProgress('QUEUED', 0);
      const reference = document.getElementById('article-reference').value.trim();
      const file = document.getElementById('article-file').files[0];
      try {
        if ((!reference && !file) || (reference && file)) {
          throw new Error('Informe exatamente uma origem: link/DOI ou arquivo.');
        }
        if (file && file.size > 10 * 1024 * 1024) {
          throw new Error('O arquivo deve ter no máximo 10 MB.');
        }
        const body = {article_reference: reference || null};
        if (file) {
          const bytes = new Uint8Array(await file.arrayBuffer());
          let binary = ''; const block = 0x8000;
          for (let index = 0; index < bytes.length; index += block) {
            binary += String.fromCharCode(...bytes.subarray(index, index + block));
          }
          body.article_reference = null;
          body.article_file = {name: file.name, mime_type: file.type, data_base64: btoa(binary)};
        }
        const response = await fetch('/api/v1/article-analyses', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(body)
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error?.message || 'Não foi possível iniciar a análise.');
        await poll(payload.status_url);
      } catch (error) { showError(error.message || 'Erro inesperado.'); }
    });
  </script>
</body>
</html>"""


def register_web_ui(
    app: Flask,
    *,
    mode_label: str = "PROTÓTIPO LOCAL — resultados dependem do backend configurado",
) -> None:
    """Registra a página sem acoplar a interface ao pipeline científico."""

    rendered = WEB_UI_HTML.replace("__MODE_LABEL__", escape(mode_label))

    @app.get("/")
    def index() -> Response:
        return Response(rendered, mimetype="text/html")
