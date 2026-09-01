        // =====================================================
        // WikiToca — Conhecimentos, Documentos e Capacitação
        // Extraído de itoca-autotoca.js. Scripts clássicos compartilham o
        // escopo global, então as funções daqui continuam visíveis para o
        // resto do app (e vice-versa: escapeHtml, showError, uiConfirm e
        // formatFileSize seguem vindo dos outros arquivos).
        // =====================================================
        let wikiEntries = [];
        let wikiDocuments = [];
        let wikiEntriesSortOrder = "az";

        const WIKI_SUBMODULES = {
            conhecimentos: { panel: 'wikiSubConhecimentos', btn: 'wikiSubBtn_conhecimentos' },
            documentos:    { panel: 'wikiSubDocumentos',    btn: 'wikiSubBtn_documentos' },
            capacitacao:   { panel: 'wikiSubCapacitacao',   btn: 'wikiSubBtn_capacitacao' },
        };
        let wikiActiveSubmodule = null;

        // Ao contrário do AutoToca, o WikiToca nunca fica sem painel: clicar no
        // botão já ativo não fecha nada.
        function toggleWikiSubmodule(key) {
            const alvo = WIKI_SUBMODULES[key];
            if (!alvo) return;
            Object.values(WIKI_SUBMODULES).forEach(({ panel, btn }) => {
                const el = document.getElementById(panel);
                if (el) el.style.display = 'none';
                const b = document.getElementById(btn);
                if (b) { b.classList.remove('btn-auto-mapping'); b.classList.add('btn-secondary'); }
            });
            const painel = document.getElementById(alvo.panel);
            if (painel) painel.style.display = 'block';
            const botao = document.getElementById(alvo.btn);
            if (botao) { botao.classList.remove('btn-secondary'); botao.classList.add('btn-auto-mapping'); }

            wikiActiveSubmodule = key;
            if (key === 'conhecimentos') loadWikiEntriesFromSearch();
            if (key === 'documentos') searchWikiDocuments();
            if (key === 'capacitacao') loadCapacitacaoSessions();
        }

        async function loadWikiTocaData() {
            toggleWikiSubmodule(wikiActiveSubmodule || 'conhecimentos');
        }

        async function loadWikiEntriesFromSearch() {
            const query = (document.getElementById('wikiSearchInput')?.value || '').trim();
            try {
                await loadWikiEntries(query ? `?q=${encodeURIComponent(query)}` : '');
            } catch (err) {
                showError('Não foi possível carregar os conhecimentos do WikiToca.');
            }
        }

        function getWikiApiErrorDetails(err, fallbackMessage) {
            const message = err?.error || fallbackMessage;
            const code = err?.error_code ? `Código: ${err.error_code}` : '';
            const details = err?.details ? `Detalhes técnicos: ${err.details}` : '';
            const hint = err?.hint ? `Como corrigir: ${err.hint}` : '';
            return [message, code, details, hint].filter(Boolean);
        }

        function renderWikiErrorBlock(lines) {
            return `<div style="background:#fef2f2; border:1px solid #fecaca; color:#991b1b; border-radius:10px; padding:10px;">${lines.map(line => `<div>${escapeHtml(line)}</div>`).join('')}</div>`;
        }

        async function loadWikiEntries(params = '') {
            const el = document.getElementById('wikiEntriesList');
            if (!el) return;
            let response;
            try {
                response = await fetch(`${API_BASE}/wikitoca/entries${params}`);
            } catch (error) {
                wikiEntries = [];
                const lines = [
                    'Falha de conexão ao carregar conhecimentos do WikiToca.',
                    `Detalhes técnicos: ${error.message}`,
                    'Como corrigir: verifique se o backend está ativo e acessível em /api/wikitoca/entries.'
                ];
                el.innerHTML = renderWikiErrorBlock(lines);
                showError(lines.join(' | '));
                return;
            }
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                wikiEntries = [];
                const lines = getWikiApiErrorDetails(err, 'Não foi possível carregar os conhecimentos do WikiToca.');
                el.innerHTML = renderWikiErrorBlock(lines);
                showError(lines.join(' | '));
                return;
            }
            wikiEntries = await response.json();
            updateWikiSortButtonLabel();
            wikiEntries = [...wikiEntries].sort((a, b) => {
                const at = (a.title || "").toLowerCase();
                const bt = (b.title || "").toLowerCase();
                if (wikiEntriesSortOrder === "za") return bt.localeCompare(at, "pt-BR");
                return at.localeCompare(bt, "pt-BR");
            });
            if (!wikiEntries.length) {
                el.innerHTML = '<p style="color:#6b7280;">Nenhum conhecimento registrado ainda.</p>';
                return;
            }
            el.innerHTML = wikiEntries.map(item => `
                <div class="wiki-entry-item" onclick="toggleWikiEntry(event, ${item.id})" data-entry-id="${item.id}">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                        <h4 style="margin:0; flex:1;">${escapeHtml(item.title || '')}</h4>
                        <i class="fas fa-chevron-down" style="color:#9ca3af; font-size:11px; margin-left:8px; margin-top:3px; transition:transform 0.2s;" id="wiki-chevron-${item.id}"></i>
                    </div>
                    <div class="wiki-meta" style="margin-top:4px;">${escapeHtml(item.category || 'Sem categoria')} • Atualizado em ${formatDateBr(item.updated_at)}${item.tags ? ` • Tags: ${escapeHtml(item.tags)}` : ''}</div>
                    <div class="wiki-entry-body" id="wiki-body-${item.id}">${escapeHtml(item.content || '')}</div>
                    <div class="wiki-entry-actions" id="wiki-actions-${item.id}">
                        <button class="btn-wiki-edit" onclick="event.stopPropagation(); openWikiEntryModal(${item.id})"><i class="fas fa-edit"></i> Editar</button>
                        <button class="btn btn-danger btn-small" onclick="event.stopPropagation(); deleteWikiEntry(${item.id})"><i class="fas fa-trash"></i> Excluir</button>
                    </div>
                </div>
            `).join('');
        }

        function _wikiDocSetProgress(pct, step) {
            const wrap = document.getElementById('wikiDocProgressWrap');
            const bar = document.getElementById('wikiDocProgressBar');
            const label = document.getElementById('wikiDocProgressStep');
            if (wrap) wrap.style.display = 'block';
            if (bar) bar.style.width = `${Math.max(5, Math.min(100, pct))}%`;
            if (label) label.textContent = step || '';
        }

        function _wikiDocHideProgress() {
            const wrap = document.getElementById('wikiDocProgressWrap');
            if (wrap) wrap.style.display = 'none';
        }

        // Acompanha uma task de background até done/error, atualizando a barra.
        // O 404 é esperado: o backend limpa a task 5 minutos após o término (e
        // ela também desaparece se o app reiniciar), então 404 significa "não
        // tenho mais notícias", não "falhou".
        async function _wikiFollowTask(taskId, onStep) {
            while (true) {
                await new Promise(r => setTimeout(r, 800));
                const resp = await fetch(`${API_BASE}/tasks/${taskId}`);
                if (resp.status === 404) throw new Error('A tarefa expirou ou foi cancelada.');
                const task = await resp.json();
                if (onStep) onStep(task.progress || 5, task.step || '');
                if (task.status === 'done') return task;
                if (task.status === 'error') throw new Error(task.error || 'Falha no processamento.');
            }
        }

        function searchWikiDocuments() {
            const q = (document.getElementById('wikiDocSearchInput')?.value || '').trim();
            const ext = (document.getElementById('wikiDocExtFilter')?.value || '').trim();
            const params = new URLSearchParams();
            if (q) params.set('q', q);
            if (ext) params.set('ext', ext);
            const query = params.toString();
            return loadWikiDocuments(query ? `?${query}` : '');
        }

        function clearWikiDocSearch() {
            const input = document.getElementById('wikiDocSearchInput');
            const filtro = document.getElementById('wikiDocExtFilter');
            if (input) input.value = '';
            if (filtro) filtro.value = '';
            searchWikiDocuments();
        }

        // `force` reprocessa também os documentos já marcados como 'ok' e 'empty'.
        // Sem esse caminho, quem instala o Tesseract DEPOIS de subir um PDF
        // escaneado fica preso: o documento ficou 'empty', e o reindex normal
        // (que só pega NULL/pending/error) nunca mais o alcança.
        async function reindexWikiDocuments(force = false) {
            const pergunta = force
                ? 'Reprocessar o texto de TODOS os documentos, inclusive os já indexados? '
                  + 'Use isto depois de instalar o Tesseract. Pode levar vários minutos.'
                : 'Reprocessar o texto dos documentos pendentes? Isso pode levar alguns minutos.';
            if (!await uiConfirm(pergunta, 'Reindexar documentos')) return;
            try {
                const resp = await fetch(`${API_BASE}/wikitoca/documents/reindex`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ force })
                });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Não foi possível iniciar a reindexação.');
                if (!payload.total) { showSuccess('Todos os documentos já estão indexados.'); return; }
                _wikiDocSetProgress(5, 'Iniciando...');
                await _wikiFollowTask(payload.task_id, _wikiDocSetProgress);
                _wikiDocHideProgress();
                showSuccess('Documentos reindexados.');
                searchWikiDocuments();
            } catch (err) {
                _wikiDocHideProgress();
                showError(err.message || 'Erro ao reindexar documentos.');
            }
        }

        async function loadWikiDocuments(params = '') {
            const el = document.getElementById('wikiDocumentsList');
            if (!el) return;
            let response = await fetch(`${API_BASE}/wikitoca/documents${params}`);
            if (!response.ok) {
                await new Promise(resolve => setTimeout(resolve, 250));
                response = await fetch(`${API_BASE}/wikitoca/documents${params}`);
            }
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                wikiDocuments = [];
                el.innerHTML = '<p style="color:#ef4444;">Erro ao carregar documentos.</p>';
                showError(err.error || 'Não foi possível carregar os documentos do WikiToca.');
                return;
            }
            wikiDocuments = await response.json();
            if (!wikiDocuments.length) {
                el.innerHTML = '<p style="color:#6b7280;">Nenhum documento cadastrado ainda.</p>';
                return;
            }
            el.innerHTML = wikiDocuments.map(doc => {
                const status = doc.extract_status || 'pending';
                const selo = {
                    pending: '<span class="wiki-index-badge" title="O texto deste arquivo ainda está sendo processado."><i class="fas fa-spinner fa-spin"></i> Indexando…</span>',
                    empty: '<span class="wiki-index-badge warn" title="Nenhum texto foi extraído deste arquivo. Se for um PDF escaneado, instale o Tesseract e use Reindexar tudo."><i class="fas fa-triangle-exclamation"></i> Sem texto extraído</span>',
                    error: '<span class="wiki-index-badge warn" title="A extração de texto falhou, ou o arquivo não foi encontrado no disco. Use Reindexar documentos para tentar de novo."><i class="fas fa-circle-exclamation"></i> Falha na indexação</span>',
                    ok: ''
                }[status] || '';
                return `
                <div class="wiki-doc-item">
                    <h4>${escapeHtml(doc.original_name || doc.title || '')}</h4>
                    <div class="wiki-meta">${formatFileSize(doc.file_size)} • ${formatDateBr(doc.updated_at)} ${selo}</div>
                    ${doc.snippet ? `<div class="wiki-doc-snippet">${doc.snippet}</div>` : ''}
                    <div style="display:flex; gap:8px;">
                        <a class="btn btn-secondary btn-small" href="${doc.file_url}" target="_blank" rel="noopener"><i class="fas fa-up-right-from-square"></i> Abrir</a>
                        <a class="btn btn-secondary btn-small" href="${doc.file_url}" download="${escapeHtml(doc.original_name || '')}"><i class="fas fa-download"></i> Baixar</a>
                        <button class="btn btn-danger btn-small" onclick="deleteWikiDocument(${doc.id})"><i class="fas fa-trash"></i></button>
                    </div>
                </div>`;
            }).join('');
        }

        function openWikiEntryModal(entryId = null) {
            const modal = document.getElementById('wikiEntryModal');
            if (!modal) return;
            const entry = wikiEntries.find(item => Number(item.id) === Number(entryId));
            document.getElementById('wikiEntryModalTitle').textContent = entry ? 'Editar conhecimento' : 'Novo conhecimento';
            document.getElementById('wikiEntryId').value = entry ? entry.id : '';
            document.getElementById('wikiEntryTitle').value = entry?.title || '';
            document.getElementById('wikiEntryCategory').value = entry?.category || '';
            document.getElementById('wikiEntryTags').value = entry?.tags || '';
            document.getElementById('wikiEntryContent').value = entry?.content || '';
            modal.classList.add('active');
        }

        function closeWikiEntryModal() {
            const modal = document.getElementById('wikiEntryModal');
            if (modal) modal.classList.remove('active');
        }

        async function saveWikiEntry(event) {
            event.preventDefault();
            const id = document.getElementById('wikiEntryId').value;
            const payload = {
                title: document.getElementById('wikiEntryTitle').value.trim(),
                category: document.getElementById('wikiEntryCategory').value.trim(),
                tags: document.getElementById('wikiEntryTags').value.trim(),
                content: document.getElementById('wikiEntryContent').value.trim()
            };
            const url = id ? `${API_BASE}/wikitoca/entries/${id}` : `${API_BASE}/wikitoca/entries`;
            const method = id ? 'PUT' : 'POST';
            let response;
            try {
                response = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            } catch (error) {
                return showError(`Falha de conexão ao salvar conhecimento. Detalhes técnicos: ${error.message}`);
            }
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                const lines = getWikiApiErrorDetails(err, 'Não foi possível salvar o conhecimento.');
                return showError(lines.join(' | '));
            }
            document.getElementById('wikiSearchInput').value = '';
            closeWikiEntryModal();
            showSuccess('Conhecimento salvo com sucesso!');
            await loadWikiTocaData();
        }

        function toggleWikiEntry(event, entryId) {
            const body = document.getElementById(`wiki-body-${entryId}`);
            const actions = document.getElementById(`wiki-actions-${entryId}`);
            const chevron = document.getElementById(`wiki-chevron-${entryId}`);
            if (!body) return;
            const isOpen = body.classList.contains('open');
            body.classList.toggle('open', !isOpen);
            actions.classList.toggle('open', !isOpen);
            if (chevron) chevron.style.transform = isOpen ? '' : 'rotate(180deg)';
        }

        async function deleteWikiEntry(entryId) {
            const confirmed = await uiConfirm('Deseja remover este conhecimento? Esta ação não pode ser desfeita.', 'Excluir conhecimento');
            if (!confirmed) return;
            const response = await fetch(`${API_BASE}/wikitoca/entries/${entryId}`, { method: 'DELETE' });
            if (!response.ok) return showError('Não foi possível excluir o conhecimento.');
            showSuccess('Conhecimento excluído.');
            await loadWikiTocaData();
        }

        async function uploadWikiDocument() {
            const fileInput = document.getElementById('wikiDocumentFile');
            const files = Array.from(fileInput?.files || []);
            if (!files.length) return showError('Selecione ao menos um arquivo para upload.');
            const formData = new FormData();
            files.forEach((file) => formData.append('files', file));
            formData.append('title', '');
            const response = await fetch(`${API_BASE}/wikitoca/documents`, { method: 'POST', body: formData });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) return showError(payload.error || 'Falha ao enviar documento(s).');

            clearWikiFileSelection();
            // A versão antiga limpava #wikiSearchInput, que agora é a busca de
            // Conhecimentos — limpar a busca do próprio submódulo é o correto.
            const docSearch = document.getElementById('wikiDocSearchInput');
            if (docSearch) docSearch.value = '';
            await searchWikiDocuments();

            if (payload.task_id) {
                _wikiDocSetProgress(5, 'Indexando documentos...');
                try {
                    await _wikiFollowTask(payload.task_id, _wikiDocSetProgress);
                } catch (err) {
                    showError(`Arquivo enviado, mas a indexação falhou: ${err.message}`);
                }
                _wikiDocHideProgress();
                await searchWikiDocuments();
            }
            showSuccess(files.length > 1 ? 'Documentos enviados com sucesso!' : 'Documento enviado com sucesso!');
        }

        async function deleteWikiDocument(documentId) {
            const confirmed = await uiConfirm('Deseja remover este documento? Esta ação não pode ser desfeita.', 'Excluir documento');
            if (!confirmed) return;
            const response = await fetch(`${API_BASE}/wikitoca/documents/${documentId}`, { method: 'DELETE' });
            if (!response.ok) return showError('Não foi possível remover o documento.');
            showSuccess('Documento removido.');
            await loadWikiTocaData();
        }

        function onWikiFileSelected(event) {
            const fileName = document.getElementById('wikiFileName');
            const uploadBtn = document.getElementById('wikiUploadBtn');
            const clearBtn = document.getElementById('wikiFileClearBtn');
            const files = Array.from(event?.target?.files || []);
            if (!fileName) return;
            if (!files.length) {
                fileName.textContent = '';
                uploadBtn?.classList.remove('wiki-upload-btn-pending');
                if (clearBtn) clearBtn.style.display = 'none';
            } else if (files.length === 1) {
                fileName.textContent = files[0].name;
                uploadBtn?.classList.add('wiki-upload-btn-pending');
                if (clearBtn) clearBtn.style.display = '';
            } else {
                fileName.textContent = `${files.length} arquivos selecionados`;
                uploadBtn?.classList.add('wiki-upload-btn-pending');
                if (clearBtn) clearBtn.style.display = '';
            }
        }

        function clearWikiFileSelection() {
            const fileInput = document.getElementById('wikiDocumentFile');
            if (fileInput) fileInput.value = '';
            const fileName = document.getElementById('wikiFileName');
            if (fileName) fileName.textContent = '';
            const clearBtn = document.getElementById('wikiFileClearBtn');
            if (clearBtn) clearBtn.style.display = 'none';
            document.getElementById('wikiUploadBtn')?.classList.remove('wiki-upload-btn-pending');
        }

        function suggestTagsFromKnowledge(title, content) {
            const stopwords = new Set(['a','o','os','as','de','da','do','das','dos','e','é','em','no','na','nos','nas','um','uma','uns','umas','para','por','com','sem','que','se','ao','aos','à','às','ou','como','mais','menos','ja','não','sim']);
            const words = `${title || ''} ${content || ''}`.toLowerCase().match(/[a-zà-ÿ0-9-]{3,}/g) || [];
            const rank = {};
            words.forEach((word) => {
                if (stopwords.has(word) || /^\d+$/.test(word)) return;
                rank[word] = (rank[word] || 0) + 1;
            });
            return Object.entries(rank)
                .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
                .slice(0, 6)
                .map(([word]) => word);
        }

        function autoFillWikiTags() {
            const title = document.getElementById('wikiEntryTitle')?.value || '';
            const content = document.getElementById('wikiEntryContent')?.value || '';
            const tagsInput = document.getElementById('wikiEntryTags');
            if (!tagsInput) return;
            const current = (tagsInput.value || '').split(',').map(tag => tag.trim()).filter(Boolean);
            const suggested = suggestTagsFromKnowledge(title, content);
            const merged = [...new Set([...current, ...suggested])].slice(0, 10);
            tagsInput.value = merged.join(', ');
        }

        function updateWikiSortButtonLabel() {
            const sortBtn = document.getElementById('wikiSortToggleBtn');
            if (!sortBtn) return;
            sortBtn.textContent = wikiEntriesSortOrder === 'za' ? 'Z-A' : 'A-Z';
        }

        function toggleWikiEntriesSort() {
            wikiEntriesSortOrder = wikiEntriesSortOrder === 'az' ? 'za' : 'az';
            updateWikiSortButtonLabel();
            // Via loadWikiEntriesFromSearch, e não loadWikiEntries() direto: a
            // versão anterior chamava sem parâmetro e a lista voltava completa,
            // perdendo em silêncio o termo que o usuário tinha buscado.
            loadWikiEntriesFromSearch();
        }

        function clearWikiSearch() {
            const input = document.getElementById('wikiSearchInput');
            if (input) input.value = '';
            loadWikiEntriesFromSearch();
        }

        function exportWikiEntries() {
            if (!wikiEntries || !wikiEntries.length) return showError('Nenhum conhecimento para exportar.');
            window.location.href = `${API_BASE}/wikitoca/entries/export-xlsx`;
        }

        function openWikiImportModal() {
            const modal = document.getElementById('wikiImportModal');
            if (!modal) return;
            const fileInput = document.getElementById('wikiXlsxInput');
            const fileLabel = document.getElementById('wikiXlsxFileName');
            const progress = document.getElementById('wikiImportProgress');
            const btn = document.getElementById('wikiImportConfirmBtn');
            if (fileInput) fileInput.value = '';
            if (fileLabel) fileLabel.textContent = 'Nenhum arquivo selecionado';
            if (progress) { progress.style.display = 'none'; progress.textContent = ''; }
            if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
            modal.classList.add('active');
        }

        function closeWikiImportModal() {
            const modal = document.getElementById('wikiImportModal');
            if (modal) modal.classList.remove('active');
        }

        function onWikiXlsxSelected(event) {
            const file = event.target.files?.[0];
            const label = document.getElementById('wikiXlsxFileName');
            const btn = document.getElementById('wikiImportConfirmBtn');
            if (file) {
                if (label) label.textContent = file.name;
                if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
            } else {
                if (label) label.textContent = 'Nenhum arquivo selecionado';
                if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
            }
        }

        async function confirmWikiXlsxImport() {
            const fileInput = document.getElementById('wikiXlsxInput');
            const file = fileInput?.files?.[0];
            if (!file) return showError('Selecione um arquivo .xlsx para importar.');
            const progress = document.getElementById('wikiImportProgress');
            const btn = document.getElementById('wikiImportConfirmBtn');
            if (progress) { progress.style.display = 'block'; progress.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Importando...'; }
            if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
            const formData = new FormData();
            formData.append('file', file);
            try {
                const res = await fetch(`${API_BASE}/wikitoca/entries/import-xlsx`, { method: 'POST', body: formData });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    if (progress) progress.innerHTML = `<span style="color:#ef4444;"><i class="fas fa-times-circle"></i> Erro: ${data.error || 'Falha na importação'}</span>`;
                    if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
                    return;
                }
                const msg = `${data.imported} conhecimento(s) importado(s) com sucesso${data.failed ? `, ${data.failed} com erro` : ''}.`;
                if (progress) progress.innerHTML = `<span style="color:#065f46;"><i class="fas fa-check-circle"></i> ${msg}</span>`;
                showSuccess(msg);
                await loadWikiTocaData();
                setTimeout(() => closeWikiImportModal(), 1800);
            } catch (err) {
                if (progress) progress.innerHTML = `<span style="color:#ef4444;"><i class="fas fa-times-circle"></i> Erro de conexão: ${err.message}</span>`;
                if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
            }
        }

        function exportWikiDocuments() {
            if (!wikiDocuments || !wikiDocuments.length) return showError('Nenhum documento para exportar.');
            window.location.href = `${API_BASE}/wikitoca/documents/export-zip`;
        }

        function openWikiDocImportModal() {
            const modal = document.getElementById('wikiDocImportModal');
            if (!modal) return;
            const fileInput = document.getElementById('wikiDocZipInput');
            const fileLabel = document.getElementById('wikiDocZipFileName');
            const progress = document.getElementById('wikiDocImportProgress');
            const btn = document.getElementById('wikiDocImportConfirmBtn');
            if (fileInput) fileInput.value = '';
            if (fileLabel) fileLabel.textContent = 'Nenhum arquivo selecionado';
            if (progress) { progress.style.display = 'none'; progress.textContent = ''; }
            if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
            modal.classList.add('active');
        }

        function closeWikiDocImportModal() {
            const modal = document.getElementById('wikiDocImportModal');
            if (modal) modal.classList.remove('active');
        }

        function onWikiDocZipSelected(event) {
            const file = event.target.files?.[0];
            const label = document.getElementById('wikiDocZipFileName');
            const btn = document.getElementById('wikiDocImportConfirmBtn');
            if (file) {
                if (label) label.textContent = file.name;
                if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
            } else {
                if (label) label.textContent = 'Nenhum arquivo selecionado';
                if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
            }
        }

        async function confirmWikiDocZipImport() {
            const fileInput = document.getElementById('wikiDocZipInput');
            const file = fileInput?.files?.[0];
            if (!file) return showError('Selecione um arquivo .zip para importar.');
            const progress = document.getElementById('wikiDocImportProgress');
            const btn = document.getElementById('wikiDocImportConfirmBtn');
            if (progress) { progress.style.display = 'block'; progress.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Importando...'; }
            if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
            const formData = new FormData();
            formData.append('file', file);
            try {
                const res = await fetch(`${API_BASE}/wikitoca/documents/import-zip`, { method: 'POST', body: formData });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    if (progress) progress.innerHTML = `<span style="color:#ef4444;"><i class="fas fa-times-circle"></i> Erro: ${data.error || 'Falha na importação'}</span>`;
                    if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
                    return;
                }
                const msg = `${data.imported} documento(s) importado(s) com sucesso.`;
                if (progress) progress.innerHTML = `<span style="color:#065f46;"><i class="fas fa-check-circle"></i> ${msg}</span>`;
                showSuccess(msg);
                await loadWikiDocuments();
                setTimeout(() => closeWikiDocImportModal(), 1800);
            } catch (err) {
                if (progress) progress.innerHTML = `<span style="color:#ef4444;"><i class="fas fa-times-circle"></i> Erro de conexão: ${err.message}</span>`;
                if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
            }
        }

        // =====================================================
        // WikiToca › Capacitação
        // =====================================================
        let capSessions = [];
        let capCurrentSession = null;   // { session, documents, messages }

        async function loadCapacitacaoSessions(keepSelection = true) {
            try {
                const resp = await fetch(`${API_BASE}/wikitoca/capacitacao/sessions`);
                if (!resp.ok) throw new Error('Falha ao carregar as capacitações.');
                capSessions = await resp.json();
            } catch (err) {
                showError(err.message || 'Não foi possível carregar as capacitações.');
                capSessions = [];
            }
            renderCapacitacaoSidebar();

            const empty = document.getElementById('capEmptyState');
            const workspace = document.getElementById('capWorkspace');
            if (!capSessions.length) {
                if (empty) empty.style.display = 'block';
                if (workspace) workspace.style.display = 'none';
                capCurrentSession = null;
                return;
            }
            if (empty) empty.style.display = 'none';
            if (workspace) workspace.style.display = 'block';

            const atual = keepSelection && capCurrentSession
                ? capSessions.find(s => s.id === capCurrentSession.session.id)
                : null;
            await selectCapacitacaoSession((atual || capSessions[0]).id);
        }

        function renderCapacitacaoSidebar() {
            const el = document.getElementById('capSessionList');
            if (!el) return;
            const contador = document.getElementById('capDrawerCount');
            if (contador) contador.textContent = `Capacitações (${capSessions.length})`;
            if (!capSessions.length) {
                el.innerHTML = '<div class="wiki-meta">Nenhuma capacitação ainda.</div>';
                return;
            }
            const ativa = capCurrentSession?.session?.id;
            // O título vem do banco sem sanitização — o backend aceita HTML cru
            // (verificado na revisão da Task 6: '<img src=x onerror=alert(1)>' é
            // armazenado literal). Todo campo do WikiToca já passa por escapeHtml;
            // aqui não é exceção.
            el.innerHTML = capSessions.map(s => `
                <div class="cap-session-card${s.id === ativa ? ' active' : ''}" onclick="selectCapacitacaoSession(${s.id})">
                    <h5>${escapeHtml(s.title || 'Nova capacitação')}</h5>
                    <div class="cap-session-meta">${s.documents_count || 0} doc(s) • ${formatDateBr(s.last_message_at || s.updated_at)}</div>
                </div>`).join('');
        }

        async function selectCapacitacaoSession(sessionId) {
            try {
                const resp = await fetch(`${API_BASE}/wikitoca/capacitacao/sessions/${sessionId}`);
                if (!resp.ok) throw new Error('Capacitação não encontrada.');
                capCurrentSession = await resp.json();
            } catch (err) {
                showError(err.message || 'Não foi possível abrir a capacitação.');
                return;
            }
            const titulo = document.getElementById('capSessionTitle');
            if (titulo) titulo.textContent = capCurrentSession.session.title || 'Nova capacitação';
            renderCapacitacaoSidebar();
            renderCapacitacaoChips();
            renderCapacitacaoMessages();
            closeCapacitacaoDrawer();
        }

        async function createCapacitacaoSession() {
            try {
                const resp = await fetch(`${API_BASE}/wikitoca/capacitacao/sessions`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Não foi possível criar a capacitação.');
                capCurrentSession = { session: payload, documents: [], messages: [] };
                await loadCapacitacaoSessions();
                document.getElementById('capFileInput')?.click();
            } catch (err) {
                showError(err.message || 'Erro ao criar capacitação.');
            }
        }

        async function renameCapacitacaoSession() {
            if (!capCurrentSession) return;
            const novo = await uiPrompt('Novo nome da capacitação:',
                capCurrentSession.session.title || '', 'Renomear capacitação');
            // openSystemDialog resolve `false` no botão Cancelar e `null` no
            // clique fora do modal — sem checar os dois, um cancelamento
            // renomearia a capacitação para "false".
            if (novo === null || novo === false) return;
            const titulo = String(novo).trim();
            if (!titulo) { showError('O título não pode ficar vazio.'); return; }
            try {
                const resp = await fetch(`${API_BASE}/wikitoca/capacitacao/sessions/${capCurrentSession.session.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: titulo })
                });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Não foi possível renomear.');
                await loadCapacitacaoSessions();
                showSuccess('Capacitação renomeada.');
            } catch (err) {
                showError(err.message || 'Erro ao renomear capacitação.');
            }
        }

        async function deleteCapacitacaoSession() {
            if (!capCurrentSession) return;
            const nome = capCurrentSession.session.title || 'esta capacitação';
            if (!await uiConfirm(`Excluir "${nome}"? Os documentos anexados e todo o histórico da conversa serão apagados.`,
                'Excluir capacitação')) return;
            try {
                const resp = await fetch(`${API_BASE}/wikitoca/capacitacao/sessions/${capCurrentSession.session.id}`,
                    { method: 'DELETE' });
                if (!resp.ok) throw new Error('Não foi possível excluir a capacitação.');
                capCurrentSession = null;
                await loadCapacitacaoSessions(false);
                showSuccess('Capacitação excluída.');
            } catch (err) {
                showError(err.message || 'Erro ao excluir capacitação.');
            }
        }

        async function clearCapacitacaoConversation() {
            if (!capCurrentSession) return;
            if (!await uiConfirm('Apagar todo o histórico desta conversa? Os documentos anexados serão mantidos.',
                'Limpar conversa')) return;
            try {
                const resp = await fetch(
                    `${API_BASE}/wikitoca/capacitacao/sessions/${capCurrentSession.session.id}/messages`,
                    { method: 'DELETE' });
                if (!resp.ok) throw new Error('Não foi possível limpar a conversa.');
                await selectCapacitacaoSession(capCurrentSession.session.id);
                showSuccess('Conversa limpa.');
            } catch (err) {
                showError(err.message || 'Erro ao limpar a conversa.');
            }
        }

        function toggleCapacitacaoDrawer() {
            document.getElementById('capSidebar')?.classList.toggle('open');
        }

        function closeCapacitacaoDrawer() {
            document.getElementById('capSidebar')?.classList.remove('open');
        }

        window.addEventListener('DOMContentLoaded', () => {
            const wikiSearchInput = document.getElementById('wikiSearchInput');
            if (wikiSearchInput) {
                wikiSearchInput.addEventListener('keydown', (event) => {
                    if (event.key === 'Enter') {
                        event.preventDefault();
                        loadWikiEntriesFromSearch();
                    }
                });
            }
            const wikiDocSearchInput = document.getElementById('wikiDocSearchInput');
            if (wikiDocSearchInput) {
                wikiDocSearchInput.addEventListener('keydown', (event) => {
                    if (event.key === 'Enter') {
                        event.preventDefault();
                        searchWikiDocuments();
                    }
                });
            }
            const wikiTitle = document.getElementById('wikiEntryTitle');
            const wikiContent = document.getElementById('wikiEntryContent');
            if (wikiTitle) wikiTitle.addEventListener('blur', autoFillWikiTags);
            if (wikiContent) wikiContent.addEventListener('blur', autoFillWikiTags);
        });
