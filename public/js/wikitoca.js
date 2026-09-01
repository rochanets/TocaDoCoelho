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
            if (key === 'capacitacao' && typeof loadCapacitacaoSessions === 'function') loadCapacitacaoSessions();
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
            el.innerHTML = wikiDocuments.map(doc => `
                <div class="wiki-doc-item">
                    <h4>${escapeHtml(doc.title || doc.original_name || 'Documento')}</h4>
                    <div class="wiki-meta">${formatFileSize(doc.file_size)} • ${formatDateBr(doc.updated_at)}</div>
                    <div style="display:flex; gap:8px;">
                        <a class="btn btn-primary btn-small" href="${doc.file_url}" target="_blank"><i class="fas fa-eye"></i> Visualizar</a>
                        <a class="btn btn-primary btn-small" href="${doc.file_url}" download="${escapeHtml(doc.original_name || '')}"><i class="fas fa-download"></i> Baixar</a>
                        <button class="btn btn-danger btn-small" onclick="deleteWikiDocument(${doc.id})"><i class="fas fa-trash"></i></button>
                    </div>
                </div>
            `).join('');
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
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                return showError(err.error || 'Falha ao enviar documento(s).');
            }
            if (fileInput) fileInput.value = '';
            const fileName = document.getElementById('wikiFileName');
            if (fileName) fileName.textContent = '';
            document.getElementById('wikiUploadBtn')?.classList.remove('wiki-upload-btn-pending');
            document.getElementById('wikiFileClearBtn')?.style && (document.getElementById('wikiFileClearBtn').style.display = 'none');
            document.getElementById('wikiSearchInput').value = '';
            showSuccess(files.length > 1 ? 'Documentos enviados com sucesso!' : 'Documento enviado com sucesso!');
            await loadWikiTocaData();
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
            loadWikiEntries();
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
