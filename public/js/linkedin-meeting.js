        // -----------------------------------------------------------------------
        // LinkedIn — Preparar Reunião
        // -----------------------------------------------------------------------
        let atLinkedinLastImportedPhotoUrl = '';
        let atLinkedinLastImportedPhotoSource = '';
        let atLinkedinImportedAt = null;
        let atLinkedinLastImportedProfileUrl = '';
        let atLinkedinForcedAccountId = null;

        function _renderLinkedInResult(data, resultArea) {
            if (!resultArea) return;
            const s = data.summary;
            const limitedDataWarning = data.limited_data
                ? `<div style="margin-bottom:12px; background:#fffbeb; border:1px solid #fcd34d; border-radius:8px; padding:10px 14px; font-size:12px; color:#92400e;">
                       <i class="fas fa-exclamation-triangle" style="margin-right:6px;"></i>
                       <strong>Dados limitados:</strong> O LinkedIn bloqueou o acesso completo ao perfil. Para um resumo mais detalhado, <strong>cole o texto do perfil</strong> no campo acima.
                   </div>`
                : '';
            if (s) {
                resultArea.innerHTML = limitedDataWarning
                    + `<div id="atLinkedinResumoCard">`
                    + _renderLinkedInSummary(s, data.source, data.fetched_from_url, data.photo_url, data.photo_source)
                    + _renderAccountContext(data.account_context)
                    + `</div>`;
                if (data.account_context && data.account_context.account) {
                    _populateAccountContextSelect(data.account_context.account.id);
                }
            } else if (data.raw) {
                resultArea.innerHTML = limitedDataWarning + `
                    <div class="settings-card">
                        <h3 style="color:#065f46; margin-bottom:12px;"><i class="fab fa-linkedin" style="margin-right:8px;"></i>Resumo Executivo</h3>
                        <pre style="white-space: pre-wrap; font-family: inherit; font-size: 13px; color: #374151;">${_escHtml(data.raw)}</pre>
                        <p style="margin-top:12px; font-size:11px; color:#9ca3af;">Fonte: ${data.source}</p>
                    </div>`;
            } else {
                resultArea.innerHTML = `<div style="padding:16px; background:#fffbeb; border:1px solid #fcd34d; border-radius:8px; color:#92400e;">
                    <i class="fas fa-exclamation-triangle" style="margin-right:6px;"></i>
                    <strong>Perfil não acessível:</strong> O LinkedIn bloqueou o acesso a este perfil. Cole o texto do perfil manualmente para gerar o resumo.
                </div>`;
            }
        }

        function _setLinkedInProgress(pct, step) {
            const bar = document.getElementById('linkedinProgressBar');
            const stepEl = document.getElementById('linkedinProgressStep');
            const pctEl = document.getElementById('linkedinProgressPct');
            if (bar) bar.style.width = Math.max(5, pct) + '%';
            if (stepEl) stepEl.textContent = step || '';
            if (pctEl) pctEl.textContent = Math.round(pct) + '%';
        }

        async function gerarResumoLinkedIn() {
            const url = (document.getElementById('atLinkedinUrl')?.value || '').trim();
            const profileText = (document.getElementById('atLinkedinProfileText')?.value || '').trim();
            const meetingCtx = (document.getElementById('atLinkedinMeetingContext')?.value || '').trim();
            const resultArea = document.getElementById('atLinkedinResultArea');
            const btn = document.getElementById('atLinkedinSummarizeBtn');

            if (!url && !profileText) {
                if (resultArea) resultArea.innerHTML = '<p style="color:#dc2626; padding: 12px; background: #fee2e2; border-radius: 8px;"><i class="fas fa-exclamation-triangle"></i> Informe a URL do LinkedIn ou cole o texto do perfil.</p>';
                return;
            }

            btn.disabled = true;
            btn.innerHTML = '<span class="ai-star-icon">✦</span> Processando...';

            // Substitui área de resultado pela barra de progresso iAta-style
            if (resultArea) {
                resultArea.innerHTML = `
                    <div style="padding:20px 4px 12px;">
                        <div style="font-size:13px; color:#6b7280; margin-bottom:12px; text-align:center;" id="linkedinProgressStep">Iniciando...</div>
                        <div style="position:relative; background:#d1fae5; border-radius:99px; height:12px; overflow:visible; margin:0 16px 6px;">
                            <div id="linkedinProgressBar" style="position:relative; height:100%; width:5%; background:linear-gradient(90deg,#059669,#10b981,#34d399); border-radius:99px; transition:width .6s ease;">
                                <img src="/images/coelho-correndo.webp" class="coelho-run" alt="">
                            </div>
                        </div>
                        <div style="display:flex; justify-content:space-between; align-items:center; padding:0 16px;">
                            <div style="font-size:12px; color:#10b981;">
                                <span style="display:inline-block; animation:iata-paw-fade 1s ease-in-out infinite;">🐾</span>
                                <span style="display:inline-block; animation:iata-paw-fade 1s ease-in-out infinite .2s;">🐾</span>
                                <span style="display:inline-block; animation:iata-paw-fade 1s ease-in-out infinite .4s;">🐾</span>
                            </div>
                            <div style="font-size:11px; color:#6b7280;" id="linkedinProgressPct">5%</div>
                        </div>
                    </div>`;
            }
            _setLinkedInProgress(5, 'Iniciando...');

            try {
                const shouldUseImportedPhoto = !!atLinkedinLastImportedPhotoUrl && (
                    !url || !atLinkedinLastImportedProfileUrl || url === atLinkedinLastImportedProfileUrl
                );
                const resp = await fetch(`${API_BASE}/linkedin/summarize`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        linkedin_url: url,
                        profile_text: profileText,
                        meeting_context: meetingCtx,
                        extension_photo_url: shouldUseImportedPhoto ? atLinkedinLastImportedPhotoUrl : '',
                        account_id: atLinkedinForcedAccountId
                    })
                });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Erro ao iniciar processamento.');
                const taskId = payload.task_id;
                if (!taskId) throw new Error('Resposta inesperada do servidor.');
                _setLinkedInProgress(10, 'Aguardando processamento...');

                // Botões Cancelar / Minimizar no topo da barra de progresso
                const _liProgressEl = document.getElementById('atLinkedinResultArea');
                _attachBgTaskControls(
                    _liProgressEl, taskId,
                    () => { /* minimizou – UI fica como está, BgTaskManager cuida */ },
                    () => {
                        btn.disabled = false;
                        btn.innerHTML = '<span class="ai-star-icon">✦</span> Gerar Resumo Executivo';
                        if (_liProgressEl) _liProgressEl.innerHTML = '<p style="color:#6b7280; padding:12px;">Cancelado.</p>';
                    }
                );

                const sourceTab = typeof _currentTab !== 'undefined' ? _currentTab : 'gestao-conta';
                BgTaskManager.register(
                    taskId,
                    `${API_BASE}/tasks/${taskId}`,
                    'Resumo LinkedIn com IA',
                    sourceTab,
                    (data) => {
                        btn.disabled = false;
                        btn.innerHTML = '<span class="ai-star-icon">✦</span> Gerar Resumo Executivo';
                        const ra = document.getElementById('atLinkedinResultArea');
                        _renderLinkedInResult(data, ra);
                    },
                    (errMsg) => {
                        btn.disabled = false;
                        btn.innerHTML = '<span class="ai-star-icon">✦</span> Gerar Resumo Executivo';
                        const ra = document.getElementById('atLinkedinResultArea');
                        if (ra) ra.innerHTML = `<p style="color:#dc2626; padding: 12px; background: #fee2e2; border-radius: 8px;"><i class="fas fa-exclamation-triangle"></i> ${errMsg || 'Erro ao gerar resumo.'}</p>`;
                    },
                    (pct, step) => _setLinkedInProgress(pct, step)
                );
            } catch (e) {
                btn.disabled = false;
                btn.innerHTML = '<span class="ai-star-icon">✦</span> Gerar Resumo Executivo';
                if (resultArea) resultArea.innerHTML = `<p style="color:#dc2626; padding: 12px; background: #fee2e2; border-radius: 8px;"><i class="fas fa-exclamation-triangle"></i> Erro de conexão: ${e.message}</p>`;
            }
        }

        function _escHtml(str) {
            return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        }

        function _renderLinkedInSummary(s, source, fetchedFromUrl, photoUrl, photoSource = '') {
            const listItems = (arr) => {
                const clean = Array.isArray(arr) ? arr.filter(i => i !== null && i !== undefined && String(i).trim()) : [];
                return clean.length
                    ? clean.map(i => `<li style="margin-bottom:4px;">${_escHtml(i)}</li>`).join('')
                    : '<li style="color:#9ca3af;">Não identificado</li>';
            };

            // O selo de origem da IA só é exibido quando gerado via SAI (mecanismo primário);
            // quando cai no fallback OpenRouter o selo fica oculto para o usuário.
            const badge = source === 'SAI'
                ? `<span style="background:#d1fae5; color:var(--t-primary); font-size:11px; padding:2px 8px; border-radius:12px; font-weight:600;">${_escHtml(source)}</span>`
                : '';
            const fetchBadge = fetchedFromUrl ? `<span style="background:#dbeafe; color:#1e40af; font-size:11px; padding:2px 8px; border-radius:12px;"><i class="fas fa-link"></i> dados da URL</span>` : '';
            const photoSourceLabelMap = {
                extension_profile_photo: 'foto da extensão',
                linkedin_og_image: 'foto og:image',
                web_search_fallback: 'foto de busca web (fallback)',
                system_contact_photo: 'foto do contato no sistema'
            };
            const photoBadge = photoSource
                ? `<span style="background:#ede9fe; color:#5b21b6; font-size:11px; padding:2px 8px; border-radius:12px;"><i class="fas fa-image"></i> ${_escHtml(photoSourceLabelMap[photoSource] || photoSource)}</span>`
                : '';

            const photoHtml = photoUrl
                ? `<img src="${_escHtml(photoUrl)}" alt="Foto de perfil"
                      style="width:80px; height:80px; border-radius:50%; object-fit:cover; border:3px solid var(--t-accent); flex-shrink:0;"
                      onerror="this.style.display='none'">`
                : `<div style="width:80px; height:80px; border-radius:50%; background:#f3f4f6; display:flex; align-items:center; justify-content:center; flex-shrink:0;">
                       <i class="fas fa-user" style="font-size:32px; color:var(--t-accent);"></i>
                   </div>`;

            return `
            <div class="settings-card atld-white" style="margin-bottom:16px;">
                <div class="atld-no-export" style="margin-bottom:12px; background:#f9fafb; border:1px solid #e5e7eb; border-radius:8px; padding:10px 12px; display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                    <span style="font-size:12px; color:#111827; font-weight:600;">Validação da foto:</span>
                    <button type="button" class="btn btn-secondary btn-small" onclick="confirmarFotoLinkedIn()"><i class="fas fa-check"></i> Confirmar foto</button>
                    <button type="button" class="btn btn-secondary btn-small" onclick="trocarFotoLinkedIn()"><i class="fas fa-link"></i> Trocar URL</button>
                    <button type="button" class="btn btn-secondary btn-small" onclick="removerFotoLinkedIn()"><i class="fas fa-user-slash"></i> Sem foto</button>
                </div>
                <!-- Cabeçalho: foto + nome + cargo + badges + botões export -->
                <div style="display:flex; align-items:center; gap:16px; margin-bottom:20px; flex-wrap:wrap;">
                    ${photoHtml}
                    <div style="flex:1; min-width:0;">
                        <h2 style="color:var(--t-primary); margin:0 0 4px; font-size:20px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${_escHtml(s.nome || '—')}</h2>
                        <p style="color:#111827; margin:0 0 8px; font-size:14px;">${_escHtml(s.cargo_atual || '')}</p>
                        <div style="display:flex; gap:6px; flex-wrap:wrap;">${badge}${fetchBadge}${photoBadge}</div>
                    </div>
                    <div class="atld-no-export" style="display:flex; gap:8px; flex-shrink:0; flex-wrap:wrap;">
                        <button class="btn btn-secondary btn-small" onclick="exportarResumoLinkedIn('jpeg')" title="Exportar como imagem JPEG">
                            <i class="fas fa-image"></i> JPEG
                        </button>
                        <button class="btn btn-secondary btn-small" onclick="exportarResumoLinkedIn('pdf')" title="Exportar como PDF">
                            <i class="fas fa-file-pdf"></i> PDF
                        </button>
                    </div>
                </div>
                <!-- Trajetória + Competências -->
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:20px;">
                    <div>
                        <h4 style="color:var(--t-primary); margin:0 0 8px; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;"><i class="fas fa-route" style="margin-right:6px;"></i>Trajetória</h4>
                        <ul style="margin:0; padding-left:18px; font-size:13px; color:#111827;">${listItems(s.trajetoria)}</ul>
                    </div>
                    <div>
                        <h4 style="color:var(--t-primary); margin:0 0 8px; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;"><i class="fas fa-star" style="margin-right:6px;"></i>Competências-chave</h4>
                        <ul style="margin:0; padding-left:18px; font-size:13px; color:#111827;">${listItems(s.competencias)}</ul>
                    </div>
                </div>
                <!-- Insights + Formação (formação mais abaixo) -->
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:20px;">
                    <div>
                        <h4 style="color:var(--t-primary); margin:0 0 8px; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;"><i class="fas fa-lightbulb" style="margin-right:6px;"></i>Insights</h4>
                        <ul style="margin:0; padding-left:18px; font-size:13px; color:#111827;">${listItems(s.insights)}</ul>
                    </div>
                    <div>
                        <h4 style="color:var(--t-primary); margin:0 0 8px; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;"><i class="fas fa-graduation-cap" style="margin-right:6px;"></i>Formação</h4>
                        <ul style="margin:0; padding-left:18px; font-size:13px; color:#111827;">${listItems(s.formacao)}</ul>
                    </div>
                </div>
            </div>
            <!-- Pontos de conversa -->
            <div class="settings-card atld-white" style="margin-bottom:16px; border-left:4px solid var(--t-primary);">
                <h4 style="color:var(--t-primary); margin:0 0 10px; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;"><i class="fas fa-comments" style="margin-right:6px;"></i>Pontos de Conversa para a Reunião</h4>
                <ul style="margin:0; padding-left:18px; font-size:13px; color:#111827;">${listItems(s.pontos_conversa)}</ul>
            </div>
            ${s.tom_sugerido ? `
            <div class="settings-card atld-white" style="border:1.5px solid var(--t-accent);">
                <h4 style="color:var(--t-primary); margin:0 0 6px; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;"><i class="fas fa-theater-masks" style="margin-right:6px;"></i>Tom Sugerido para a Reunião</h4>
                <p style="margin:0; font-size:14px; color:#111827; font-weight:500;">${_escHtml(s.tom_sugerido)}</p>
            </div>` : ''}`;
        }

        function _renderAccountContext(ac) {
            if (!ac || !ac.account) return '';
            const accName = _escHtml(ac.account.name || 'Conta');

            // Bloco a) momento de mercado
            const marketHtml = ac.market_moment
                ? `<p style="margin:0; font-size:13px; color:#111827; line-height:1.6;">${_escHtml(ac.market_moment)}</p>`
                : `<p style="margin:0; font-size:13px; color:#9ca3af;">Momento de mercado indisponível no momento.</p>`;

            // Bloco c) serviços Stefanini
            let svcHtml;
            const services = Array.isArray(ac.stefanini_services)
                ? ac.stefanini_services.filter(s => s && String(s.delivery_name || '').trim())
                : [];
            if (services.length) {
                svcHtml = '<ul style="margin:0; padding-left:18px; font-size:13px; color:#111827;">'
                    + services.map(s => {
                        const owner = s.stf_owner ? ` <span style="color:#6b7280;">(${_escHtml(s.stf_owner)})</span>` : '';
                        const rev = s.revenue ? ` — <strong>${_escHtml(s.revenue)}</strong>` : '';
                        return `<li style="margin-bottom:4px;">${_escHtml(s.delivery_name)}${owner}${rev}</li>`;
                    }).join('')
                    + '</ul>';
            } else {
                svcHtml = '<p style="margin:0; font-size:13px; color:#9ca3af;">Nenhum serviço Stefanini mapeado para esta conta.</p>';
            }

            // Bloco b) relacionamento com o contato (condicional)
            let relHtml = '';
            if (ac.contact_found && ac.relationship_summary) {
                relHtml = `
                    <div style="margin-bottom:16px;">
                        <h4 style="color:var(--t-primary); margin:0 0 8px; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;"><i class="fas fa-handshake" style="margin-right:6px;"></i>Relacionamento com o Contato</h4>
                        <p style="margin:0; font-size:13px; color:#111827; line-height:1.6;">${_escHtml(ac.relationship_summary)}</p>
                    </div>`;
            } else if (!ac.contact_found) {
                relHtml = `
                    <div style="margin-bottom:16px; background:#fffbeb; border:1px solid #fcd34d; border-radius:8px; padding:10px 12px;">
                        <span style="font-size:12px; color:#92400e;"><i class="fas fa-info-circle" style="margin-right:6px;"></i>Contato não vinculado a um contato cadastrado no sistema — exibindo apenas o contexto da conta.</span>
                    </div>`;
            }

            return `
            <div class="settings-card atld-white" style="margin-bottom:16px; border-left:4px solid var(--t-primary);">
                <div style="display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:14px; flex-wrap:wrap;">
                    <h3 style="color:var(--t-primary); margin:0; font-size:15px;"><i class="fas fa-building" style="margin-right:8px;"></i>Contexto da Conta: ${accName}</h3>
                    <select id="atAccountContextSelect" class="atld-no-export" onchange="onAtAccountContextChange(this.value)" style="font-size:12px; padding:4px 8px; border:1px solid #d1d5db; border-radius:6px; background:white; color:#111827; max-width:220px;">
                        <option value="${ac.account.id}" selected>${accName}</option>
                    </select>
                </div>
                ${relHtml}
                <div style="margin-bottom:16px;">
                    <h4 style="color:var(--t-primary); margin:0 0 8px; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;"><i class="fas fa-chart-line" style="margin-right:6px;"></i>Momento de Mercado</h4>
                    ${marketHtml}
                </div>
                <div>
                    <h4 style="color:var(--t-primary); margin:0 0 8px; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;"><i class="fas fa-briefcase" style="margin-right:6px;"></i>O que temos na conta (Serviços Stefanini)</h4>
                    ${svcHtml}
                </div>
            </div>`;
        }

        async function _populateAccountContextSelect(currentAccountId) {
            const select = document.getElementById('atAccountContextSelect');
            if (!select) return;
            try {
                const resp = await fetch(`${API_BASE}/accounts`);
                if (!resp.ok) return;
                const accounts = await resp.json();
                const options = ['<option value="">Nenhuma conta (limpar)</option>'];
                (Array.isArray(accounts) ? accounts : []).forEach(acc => {
                    const selected = String(acc.id) === String(currentAccountId) ? ' selected' : '';
                    options.push(`<option value="${acc.id}"${selected}>${_escHtml(acc.name || 'Conta sem nome')}</option>`);
                });
                select.innerHTML = options.join('');
            } catch (e) {
                // Mantém o select com a opção única já renderizada se a busca falhar
            }
        }

        function onAtAccountContextChange(value) {
            atLinkedinForcedAccountId = value ? value : null;
            gerarResumoLinkedIn();
        }

        function confirmarFotoLinkedIn() {
            showSuccess('Foto confirmada para este resumo.');
        }

        function trocarFotoLinkedIn() {
            const current = atLinkedinLastImportedPhotoUrl || '';
            const nextUrl = (prompt('Cole a URL da nova foto de perfil:', current) || '').trim();
            if (!nextUrl) return;
            atLinkedinLastImportedPhotoUrl = nextUrl;
            atLinkedinLastImportedPhotoSource = 'manual_override';
            gerarResumoLinkedIn();
        }

        function removerFotoLinkedIn() {
            atLinkedinLastImportedPhotoUrl = '';
            atLinkedinLastImportedPhotoSource = 'manual_remove';
            gerarResumoLinkedIn();
        }

        function _loadImageEl(src) {
            return new Promise((resolve) => {
                if (!src) { resolve(null); return; }
                const img = new Image();
                img.crossOrigin = 'anonymous';
                img.onload = () => resolve(img);
                img.onerror = () => resolve(null);
                img.src = src;
            });
        }

        async function exportarResumoLinkedIn(formato) {
            const card = document.getElementById('atLinkedinResumoCard');
            if (!card) return;

            if (typeof html2canvas === 'undefined') {
                alert('Biblioteca de exportação ainda carregando. Aguarde um instante e tente novamente.');
                return;
            }

            const btn = (typeof event !== 'undefined' && event) ? event.currentTarget : null;
            const btnOriginalHtml = btn ? btn.innerHTML : '';
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Exportando...';
            }

            // Esconde elementos de interação (validação de foto, botões de export, seletor de conta)
            const hiddenEls = Array.from(card.querySelectorAll('.atld-no-export'));
            const prevDisplay = hiddenEls.map(el => el.style.display);
            hiddenEls.forEach(el => { el.style.display = 'none'; });

            try {
                const nomeEl = card.querySelector('h2');
                const nomeArq = (nomeEl?.textContent || 'resumo-linkedin').trim().replace(/\s+/g, '-').toLowerCase();

                const canvas = await html2canvas(card, {
                    scale: 2,
                    useCORS: true,
                    backgroundColor: '#ffffff',
                    logging: false
                });

                // Marca d'água: logo Toca do Coelho (inferior direita) + usuário logado (superior direita)
                const ctx = canvas.getContext('2d');
                const scale = canvas.width / card.offsetWidth;
                const pad = 14 * scale;

                const [logoImg, userImg] = await Promise.all([
                    _loadImageEl('/logo-coelho.png'),
                    _loadImageEl((typeof userProfile === 'object' && userProfile && userProfile.photo_url) || '')
                ]);

                if (logoImg && logoImg.naturalHeight) {
                    const logoH = 40 * scale;
                    const logoW = logoH * (logoImg.naturalWidth / logoImg.naturalHeight);
                    ctx.drawImage(logoImg, canvas.width - logoW - pad, canvas.height - logoH - pad, logoW, logoH);
                }

                const userName = (typeof userProfile === 'object' && userProfile && (userProfile.nickname || userProfile.full_name)) || '';
                if (userImg || userName) {
                    const avatarSize = 40 * scale;
                    const avX = canvas.width - avatarSize - pad;
                    const avY = pad;
                    if (userImg && userImg.naturalHeight) {
                        ctx.save();
                        ctx.beginPath();
                        ctx.arc(avX + avatarSize / 2, avY + avatarSize / 2, avatarSize / 2, 0, Math.PI * 2);
                        ctx.closePath();
                        ctx.clip();
                        ctx.drawImage(userImg, avX, avY, avatarSize, avatarSize);
                        ctx.restore();
                    }
                    if (userName) {
                        ctx.font = `${11 * scale}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
                        ctx.fillStyle = '#111827';
                        ctx.textAlign = 'center';
                        ctx.fillText(userName, avX + avatarSize / 2, avY + avatarSize + 16 * scale);
                    }
                }

                // Limita a largura final da exportação a 1200px (reduz o tamanho do arquivo)
                const MAX_EXPORT_WIDTH = 1200;
                let finalCanvas = canvas;
                if (canvas.width > MAX_EXPORT_WIDTH) {
                    const ratio = MAX_EXPORT_WIDTH / canvas.width;
                    const resized = document.createElement('canvas');
                    resized.width = MAX_EXPORT_WIDTH;
                    resized.height = Math.round(canvas.height * ratio);
                    resized.getContext('2d').drawImage(canvas, 0, 0, resized.width, resized.height);
                    finalCanvas = resized;
                }

                if (formato === 'jpeg') {
                    const link = document.createElement('a');
                    link.download = `${nomeArq}.jpg`;
                    link.href = finalCanvas.toDataURL('image/jpeg', 0.92);
                    link.click();
                } else {
                    // PDF via jsPDF
                    if (typeof window.jspdf === 'undefined') {
                        alert('Biblioteca PDF ainda carregando. Aguarde um instante e tente novamente.');
                        return;
                    }
                    const { jsPDF } = window.jspdf;
                    const imgW = 210; // A4 largura em mm
                    const imgH = (finalCanvas.height * imgW) / finalCanvas.width;
                    const pdf = new jsPDF({ orientation: imgH > imgW ? 'p' : 'l', unit: 'mm', format: 'a4' });
                    const pageH = pdf.internal.pageSize.getHeight();
                    let yPos = 0;
                    while (yPos < imgH) {
                        if (yPos > 0) pdf.addPage();
                        pdf.addImage(finalCanvas.toDataURL('image/jpeg', 0.92), 'JPEG', 0, -yPos, imgW, imgH);
                        yPos += pageH;
                    }
                    pdf.save(`${nomeArq}.pdf`);
                }
            } catch (e) {
                console.error('[exportarResumoLinkedIn] erro:', e);
                alert('Falha ao exportar o relatório: ' + (e?.message || e));
            } finally {
                hiddenEls.forEach((el, i) => { el.style.display = prevDisplay[i] || ''; });
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = btnOriginalHtml;
                }
            }
        }

        // -----------------------------------------------------------------------
        // LinkedIn — Importar da extensão
        // -----------------------------------------------------------------------

        function abrirGuiaLinkedIn() {
            document.getElementById('linkedinGuideModal').style.display = 'block';
            document.body.style.overflow = 'hidden';
        }

        function fecharGuiaLinkedIn() {
            document.getElementById('linkedinGuideModal').style.display = 'none';
            document.body.style.overflow = '';
        }

        document.getElementById('linkedinGuideModal')?.addEventListener('click', function(e) {
            if (e.target === this) fecharGuiaLinkedIn();
        });

        async function importarPerfilLinkedIn() {
            const btn = document.getElementById('atLinkedinImportBtn');
            const resultArea = document.getElementById('atLinkedinResultArea');
            const profileTextArea = document.getElementById('atLinkedinProfileText');

            // Verifica se extensão está instalada
            const installed = await _checkAutoTocaExtensionInstalled();
            if (!installed) {
                abrirGuiaLinkedIn();
                return;
            }

            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-circle-notch fa-spin" style="margin-right:5px;"></i> Buscando perfil...';

            try {
                const result = await _sendAutoTocaCommand({ command: 'get_linkedin_profile' });

                if (!result?.ok) {
                    // Nenhum perfil capturado ainda — abre o guia para orientar
                    resultArea.innerHTML = `<div style="background:#fffbeb; border:1px solid #fcd34d; border-radius:8px; padding:12px 16px; font-size:13px; color:#92400e;">
                        <i class="fas fa-info-circle" style="margin-right:6px;"></i>
                        <strong>Nenhum perfil capturado ainda.</strong> Abra um perfil no LinkedIn e clique no botão
                        "<strong style="background:linear-gradient(135deg,#9333ea,#60a5fa,#22d3ee);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">✦</strong> Analisar com AutoToca" que aparece na página.
                        <button onclick="abrirGuiaLinkedIn()" class="btn btn-secondary btn-small" style="margin-left:10px;">Ver tutorial</button>
                    </div>`;
                    return;
                }

                // Popula os campos e gera o resumo automaticamente
                if (profileTextArea) profileTextArea.value = result.profileText || '';
                const urlInput = document.getElementById('atLinkedinUrl');
                if (urlInput && result.profileUrl) urlInput.value = result.profileUrl;
                atLinkedinLastImportedProfileUrl = (result.profileUrl || '').trim();
                atLinkedinLastImportedPhotoUrl = (result.profilePhotoUrl || '').trim();
                atLinkedinLastImportedPhotoSource = result.profilePhotoSource || 'extension_payload';
                atLinkedinImportedAt = result.capturedAt || new Date().toISOString();

                const photoImported = atLinkedinLastImportedPhotoUrl ? 'com foto do perfil' : 'sem foto detectada';

                resultArea.innerHTML = `<div style="background:#ecfdf5; border:1px solid #6ee7b7; border-radius:8px; padding:12px 16px; font-size:13px; color:#065f46; margin-bottom:8px; display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                    <i class="fas fa-check-circle" style="margin-right:2px;"></i>
                    <span><strong>Perfil importado!</strong> Capturado em ${new Date(atLinkedinImportedAt).toLocaleTimeString('pt-BR')} (${photoImported}). Revise os campos e clique em <strong>"Gerar Resumo Executivo"</strong> quando estiver pronto.</span>
                    <button class="btn btn-auto-mapping btn-small" onclick="gerarResumoLinkedIn()" style="margin-left:auto;">
                        <span class="ai-star-icon">✦</span> Gerar Resumo Executivo
                    </button>
                </div>`;

                // Não dispara o resumo automaticamente — aguarda o usuário confirmar (clicar em "Gerar Resumo Executivo")

            } catch (e) {
                resultArea.innerHTML = `<p style="color:#dc2626; background:#fee2e2; padding:10px; border-radius:8px; font-size:13px;">
                    <i class="fas fa-exclamation-triangle" style="margin-right:6px;"></i> Erro ao comunicar com a extensão: ${e.message}
                </p>`;
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i class="fab fa-linkedin" style="margin-right:5px;"></i> Importar da Extensão';
            }
        }

        async function _checkAutoTocaExtensionInstalled() {
            return new Promise(resolve => {
                const timeout = setTimeout(() => resolve(false), 800);
                window.addEventListener('autotoca-extension-pong', () => {
                    clearTimeout(timeout); resolve(true);
                }, { once: true });
                window.dispatchEvent(new CustomEvent('autotoca-extension-ping'));
            });
        }

        async function _sendAutoTocaCommand(detail) {
            return new Promise((resolve, reject) => {
                const timeout = setTimeout(() => reject(new Error('Extensão não respondeu a tempo.')), 5000);
                window.addEventListener('autotoca-extension-result', e => {
                    clearTimeout(timeout); resolve(e.detail);
                }, { once: true });
                window.dispatchEvent(new CustomEvent('autotoca-extension-command', { detail }));
            });
        }

        async function verLogsExtensao() {
            const modal = document.getElementById('extensionLogsModal');
            const body  = document.getElementById('extensionLogsBody');
            modal.style.display = 'flex';
            body.innerHTML = '<div style="color:#6b7280; text-align:center; padding:20px;"><i class="fas fa-circle-notch fa-spin"></i> Buscando logs...</div>';

            const installed = await _checkAutoTocaExtensionInstalled();
            if (!installed) {
                body.innerHTML = '<div style="color:#dc2626; padding:12px; background:#fee2e2; border-radius:8px; font-size:13px;"><i class="fas fa-exclamation-triangle" style="margin-right:6px;"></i>Extensão não encontrada. Instale e recarregue a página do LinkedIn.</div>';
                return;
            }

            try {
                const result = await _sendAutoTocaCommand({ command: 'get_extension_logs' });
                const logs = result?.logs || [];
                if (logs.length === 0) {
                    body.innerHTML = '<div style="color:#6b7280; padding:12px; font-size:13px;">Nenhum log registrado ainda. Navegue por um perfil no LinkedIn e volte aqui.</div>';
                    return;
                }

                const levelColors = { info: '#065f46', warn: '#92400e', error: '#dc2626' };
                const levelBg     = { info: '#f0fdf4', warn: '#fffbeb', error: '#fee2e2' };
                const reversed = [...logs].reverse();
                body.innerHTML = reversed.map(e => {
                    const ts = new Date(e.ts).toLocaleTimeString('pt-BR', { hour:'2-digit', minute:'2-digit', second:'2-digit' });
                    const extras = Object.entries(e).filter(([k]) => !['ts','level','msg','url'].includes(k));
                    const extraHtml = extras.length ? `<div style="margin-top:4px; font-size:10px; color:#6b7280; font-family:monospace; background:#f3f4f6; padding:3px 6px; border-radius:4px; word-break:break-all;">${extras.map(([k,v])=>`${k}: ${JSON.stringify(v)}`).join(' | ')}</div>` : '';
                    const urlShort = (e.url || '').replace('https://www.linkedin.com','').replace('https://','').slice(0, 60);
                    return `<div style="padding:8px 10px; border-radius:6px; background:${levelBg[e.level]||'#f9fafb'}; border-left:3px solid ${levelColors[e.level]||'#9ca3af'}; margin-bottom:6px;">
                        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                            <span style="font-size:10px; color:#9ca3af; flex-shrink:0;">${ts}</span>
                            <span style="font-size:10px; font-weight:700; color:${levelColors[e.level]||'#374151'}; text-transform:uppercase;">${e.level}</span>
                            <span style="font-size:12px; color:#1f2937; font-weight:500;">${e.msg}</span>
                        </div>
                        ${urlShort ? `<div style="font-size:10px; color:#9ca3af; margin-top:2px;">${urlShort}</div>` : ''}
                        ${extraHtml}
                    </div>`;
                }).join('');
            } catch (err) {
                body.innerHTML = `<div style="color:#dc2626; font-size:13px; padding:10px;">Erro ao buscar logs: ${err.message}</div>`;
            }
        }

        async function limparLogsExtensao() {
            if (!await uiConfirm('Apagar todos os logs da extensão?', 'Limpar Logs')) return;
            try {
                await _sendAutoTocaCommand({ command: 'clear_extension_logs' });
                document.getElementById('extensionLogsBody').innerHTML = '<div style="color:#6b7280; padding:12px; font-size:13px;">Logs apagados.</div>';
            } catch (e) {
                alert('Erro: ' + e.message);
            }
        }
