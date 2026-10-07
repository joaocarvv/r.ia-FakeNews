/* Local library, explicit comparison sets, and reopening persisted analyses. */
(() => {
  const chosen = new Set();
  const status = document.getElementById('library-status');
  const list = document.getElementById('library-items');
  const node = (tag, text) => { const value = document.createElement(tag); if (text) value.textContent = text; return value; };
  const button = (text, action) => { const value = node('button', text); value.type = 'button'; value.className = 'secondary'; value.addEventListener('click', action); return value; };
  const request = async (url, options) => {
    const response = await fetch(url, options); const payload = await response.json();
    if (!response.ok) throw new Error(payload.error?.message || 'A operação não foi concluída.');
    return payload;
  };
  const post = (url, body) => request(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const references = id => document.getElementById(id).value.split(/\r?\n/).map(text => text.trim()).filter(Boolean);
  const files = async id => {
    const selected = [...document.getElementById(id).files];
    if (selected.reduce((sum, file) => sum + file.size, 0) > 25 * 1024 * 1024) throw new Error('Use até 25 MB de PDFs por envio.');
    return Promise.all(selected.map(async file => ({name:file.name, mime_type:'application/pdf', data_base64:await fileToBase64(file)})));
  };
  function updateChosen() {
    document.getElementById('manual-comparison-selected').textContent = `${chosen.size} artigo(s) da biblioteca escolhido(s). Links e PDFs serão adicionados a esse conjunto.`;
  }
  window.getComparisonSelection = async () => {
    const mode = document.querySelector('input[name="comparison-mode"]:checked').value;
    if (mode === 'AUTOMATIC') return {mode};
    const payload = {mode, article_ids:[...chosen], references:references('comparison-references'), files:await files('comparison-files')};
    const count = payload.article_ids.length + payload.references.length + payload.files.length;
    if (count < 1 || count > 20) throw new Error('Escolha de 1 a 20 artigos para a comparação manual.');
    return payload;
  };
  window.restoreComparisonSelection = comparison => {
    if (!comparison) return;
    chosen.clear(); (comparison.article_ids || []).forEach(id => chosen.add(id));
    const mode = document.querySelector(`input[name="comparison-mode"][value="${comparison.mode === 'MANUAL' ? 'MANUAL' : 'AUTOMATIC'}"]`);
    mode.checked = true; mode.dispatchEvent(new Event('change'));
    document.getElementById('comparison-references').value = '';
    document.getElementById('comparison-files').value = '';
    updateChosen();
  };
  document.querySelectorAll('input[name="comparison-mode"]').forEach(input => input.addEventListener('change', () => {
    const manual = document.querySelector('input[name="comparison-mode"]:checked').value === 'MANUAL';
    document.getElementById('manual-comparison-fields').hidden = !manual;
    document.querySelector('.depth-options').hidden = manual;
    document.getElementById('research-estimate').hidden = manual;
  }));
  async function refresh() {
    const data = await request('/api/v1/library/articles?q=' + encodeURIComponent(document.getElementById('library-query').value));
    list.replaceChildren();
    const filtering = Boolean(document.getElementById('library-query').value.trim());
    document.getElementById('library-count').textContent = `${data.articles.length} ${data.articles.length === 1 ? 'artigo' : 'artigos'}${filtering ? ' encontrados' : ''}`;
    if (!data.articles.length) {
      const empty = node('div'); empty.className = 'library-empty';
      empty.append(node('strong', filtering ? 'Nenhum artigo encontrado' : 'Sua próxima leitura começa aqui'));
      empty.append(node('p', filtering ? 'Tente outro termo no título, texto ou notas dos seus artigos.' : 'Guarde referências ou PDFs para reunir suas fontes e retomar as análises.'));
      list.append(empty);
    }
    data.articles.forEach(article => {
      const card = node('article'); card.className = 'finding';
      card.append(node('h3', article.title));
      const metadata = node('p', [article.journal, article.publication_date, article.pmid ? `PMID ${article.pmid}` : null, article.doi ? `DOI ${article.doi}` : null].filter(Boolean).join(' · ')); metadata.className = 'library-meta'; card.append(metadata);
      const scope = node('p', /FULL_TEXT/.test(article.content_scope) ? 'Texto completo guardado' : 'Resumo ou texto parcial guardado'); scope.className = 'library-scope'; card.append(scope);
      const selection = node('label'); const toggle = node('input'); toggle.type = 'checkbox'; toggle.style.width = 'auto'; toggle.checked = chosen.has(article.article_id);
      toggle.addEventListener('change', () => { toggle.checked ? chosen.add(article.article_id) : chosen.delete(article.article_id); updateChosen(); });
      selection.append(toggle, document.createTextNode(' Usar como referência na comparação manual')); card.append(selection);
      const actions = node('div'); actions.className = 'actions';
      actions.append(button('Ler fonte guardada', async () => {
        try {
          const saved = await request(`/api/v1/library/articles/${article.article_id}`);
          document.getElementById('preview-kicker').textContent = 'Biblioteca';
          document.getElementById('preview-title').textContent = article.title;
          document.getElementById('preview-meta').textContent = article.content_scope;
          const body = document.getElementById('preview-body'); body.replaceChildren();
          const text = node('div', saved.document.text); text.className = 'page-text'; body.append(text);
          document.getElementById('preview-dialog').showModal();
        } catch (error) { status.textContent = error.message; }
      }));
      if (article.analysis_ids.length) {
        const select = node('select'); select.setAttribute('aria-label', 'Análise guardada');
        article.analysis_ids.slice().reverse().forEach((id, index) => { const option = node('option', `Análise ${article.analysis_ids.length - index} · ${id.slice(0,8)}`); option.value = id; select.append(option); });
        actions.append(select, button('Abrir análise', async () => {
          try { await window.openAnalysisSession(select.value); } catch (error) { status.textContent = error.message; }
        }));
      }
      actions.append(button('Iniciar nova leitura', async () => {
        try { const job = await post(`/api/v1/library/articles/${article.article_id}/analyses`, {}); await window.openAnalysisSession(job.analysis_id); }
        catch (error) { status.textContent = error.message; }
      }));
      if (article.has_original_file) {
        const download = node('a', 'Baixar arquivo original'); download.href = `/api/v1/library/articles/${article.article_id}/file`; actions.append(download);
      }
      card.append(actions);
      const notes = node('details'); notes.append(node('summary','Notas e etiquetas'));
      const noteInput = node('textarea'); noteInput.value = article.notes; noteInput.maxLength = 10000; noteInput.setAttribute('aria-label', 'Notas do artigo');
      const tags = node('input'); tags.value = article.tags.join(', '); tags.placeholder = 'Etiquetas separadas por vírgula'; tags.setAttribute('aria-label','Etiquetas do artigo');
      notes.append(noteInput, tags, button('Guardar notas', async () => {
        try {
          await request(`/api/v1/library/articles/${article.article_id}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({notes:noteInput.value, tags:tags.value.split(',').map(text => text.trim()).filter(Boolean)})});
          status.textContent = 'Notas guardadas.';
        } catch (error) { status.textContent = error.message; }
      }));
      card.append(notes); list.append(card);
    });
    updateChosen();
  }
  window.refreshArticleLibrary = () => refresh().catch(error => { status.textContent = error.message; });
  document.getElementById('library-refresh').addEventListener('click', window.refreshArticleLibrary);
  document.getElementById('library-query').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); window.refreshArticleLibrary(); } });
  document.getElementById('library-add').addEventListener('click', async event => {
    const control = event.currentTarget; control.disabled = true;
    try {
      const refs = references('library-references'), uploads = await files('library-files');
      if (!refs.length && !uploads.length) throw new Error('Informe uma referência ou escolha um PDF.');
      if (refs.length + uploads.length > 20) throw new Error('Guarde até 20 artigos por envio.');
      const inputs = [...refs.map(reference => ({article_reference:reference})), ...uploads.map(file => ({article_file:file}))];
      let saved = 0;
      for (const input of inputs) { status.textContent = `Guardando artigo ${saved + 1} de ${inputs.length}…`; await post('/api/v1/library/articles', input); saved++; }
      document.getElementById('library-references').value = ''; document.getElementById('library-files').value = '';
      status.textContent = `${saved} artigo(s) guardado(s).`; await refresh();
    } catch (error) { status.textContent = error.message; await window.refreshArticleLibrary(); }
    finally { control.disabled = false; }
  });
  document.getElementById('save-current-article').addEventListener('click', async () => {
    try { await post('/api/v1/library/articles', {analysis_id:activeAnalysisId}); status.textContent = 'Artigo e análise guardados.'; await refresh(); }
    catch (error) { status.textContent = error.message; }
  });
  window.refreshArticleLibrary();
})();
