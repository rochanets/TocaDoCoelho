        // =========================================================
        // HOME — Dashboard Executivo (ECharts)
        // =========================================================
        const HOME_STATE = {
            period: 'all',
            months: [],
            availableMonths: [],
            charts: {},
            chartOptions: {},
            chartTitles: {
                chartFaturamento: 'Top 10 Faturamento Mensal',
                chartFaturamentoUnico: 'Top 10 Faturamento Único',
                chartInteracoes: 'Top 10 Contas com Mais Interações',
                chartTargetMenor: 'Top 5 Contas Target com Menor Nível de Interação',
                chartCargo: 'Interações por Cargo',
                chartEvolucao: 'Evolução Mensal das Interações',
                chartCanal: 'Canal de Relacionamento',
                chartHeatmap: 'Mapa de Atividade por Dia da Semana',
                chartFunil: 'Funil de Engajamento',
                chartTempo: 'Tempo Médio Sem Contato (dias)',
                chartNovos: 'Novos Contatos Criados por Mês',
            },
            lastInsights: null,
            modalChart: null,
            firstLoad: true,
            resizeHandlerBound: false,
            cardActionsInjected: false,
            includeArchived: false,
            includeCold: false,
        };

        const HOME_PALETTE = ['#22d3ee', '#3b82f6', '#a855f7', '#ec4899', '#f97316', '#facc15', '#22c55e', '#14b8a6'];

        function _homeFmtMonthLabel(ym) {
            if (!ym || !/^\d{4}-\d{2}$/.test(ym)) return ym || '';
            const [y, m] = ym.split('-').map(Number);
            const meses = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];
            return `${meses[m - 1]}/${String(y).slice(2)}`;
        }
        function _homeFmtMonthLong(ym) {
            if (!ym || !/^\d{4}-\d{2}$/.test(ym)) return ym || '';
            const [y, m] = ym.split('-').map(Number);
            const meses = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];
            return `${meses[m - 1]}/${y}`;
        }
        function _homeFmtBRL(cents) {
            const v = Number(cents || 0) / 100;
            if (v >= 1_000_000) return `R$ ${(v / 1_000_000).toFixed(1).replace('.', ',')}M`;
            if (v >= 1_000) return `R$ ${(v / 1_000).toFixed(0)}k`;
            return `R$ ${v.toFixed(0)}`;
        }
        function _homeShortName(name, max = 18) {
            if (!name) return '—';
            const s = String(name).trim();
            return s.length > max ? s.slice(0, max - 1) + '…' : s;
        }

        function _homeDisposeAllCharts() {
            Object.keys(HOME_STATE.charts).forEach(key => {
                try { HOME_STATE.charts[key]?.dispose(); } catch (_) {}
            });
            HOME_STATE.charts = {};
        }

        function _homeInitChart(id) {
            const el = document.getElementById(id);
            if (!el) return null;
            try {
                if (HOME_STATE.charts[id]) {
                    HOME_STATE.charts[id].dispose();
                }
            } catch (_) {}
            // garante container vivo (caso tenha sido substituído por empty state antes)
            if (el.querySelector('.home-empty')) el.innerHTML = '';
            const chart = echarts.init(el, null, { renderer: 'canvas' });
            HOME_STATE.charts[id] = chart;
            // intercept setOption to also store the option for later (maximize modal)
            const origSetOption = chart.setOption.bind(chart);
            chart.setOption = (option, ...rest) => {
                HOME_STATE.chartOptions[id] = option;
                return origSetOption(option, ...rest);
            };
            return chart;
        }

        function _homeRenderEmpty(id, msg = 'Sem dados no período') {
            const el = document.getElementById(id);
            if (!el) return;
            if (HOME_STATE.charts[id]) {
                try { HOME_STATE.charts[id].dispose(); } catch (_) {}
                delete HOME_STATE.charts[id];
            }
            HOME_STATE.chartOptions[id] = null;
            el.innerHTML = `<div class="home-empty"><i class="fas fa-chart-simple"></i><span>${escapeHtml(msg)}</span></div>`;
        }

        function _homeInjectCardActions() {
            if (HOME_STATE.cardActionsInjected) return;
            const cards = document.querySelectorAll('#home .home-card');
            cards.forEach(card => {
                const head = card.querySelector('.home-card-head');
                const chartEl = card.querySelector('.home-chart');
                if (!head || !chartEl || head.querySelector('.home-card-actions')) return;
                const chartId = chartEl.id;
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'home-card-actions';
                btn.title = 'Expandir';
                btn.setAttribute('aria-label', 'Expandir gráfico');
                btn.innerHTML = '<i class="fas fa-up-right-and-down-left-from-center"></i>';
                btn.onclick = () => openHomeChartModal(chartId);
                head.appendChild(btn);
            });
            HOME_STATE.cardActionsInjected = true;
        }

        function _homeOpenModal(title, bodyHtml) {
            const modal = document.getElementById('homeModal');
            const titleEl = document.getElementById('homeModalTitle');
            const bodyEl = document.getElementById('homeModalBody');
            if (!modal || !bodyEl || !titleEl) return;
            // Dispose any previous modal chart
            if (HOME_STATE.modalChart) {
                try { HOME_STATE.modalChart.dispose(); } catch (_) {}
                HOME_STATE.modalChart = null;
            }
            titleEl.textContent = title || '';
            bodyEl.innerHTML = bodyHtml;
            modal.classList.add('active');
            document.addEventListener('keydown', _homeModalEsc);
        }
        function _homeModalEsc(e) { if (e.key === 'Escape') closeHomeModal(); }
        function closeHomeModal() {
            const modal = document.getElementById('homeModal');
            if (!modal) return;
            modal.classList.remove('active');
            if (HOME_STATE.modalChart) {
                try { HOME_STATE.modalChart.dispose(); } catch (_) {}
                HOME_STATE.modalChart = null;
            }
            document.removeEventListener('keydown', _homeModalEsc);
        }

        function openHomeChartModal(chartId) {
            const title = HOME_STATE.chartTitles[chartId] || 'Gráfico';
            const option = HOME_STATE.chartOptions[chartId];
            if (!option) {
                _homeOpenModal(title, '<div class="home-empty" style="min-height:60vh;"><i class="fas fa-chart-simple"></i><span>Sem dados para exibir.</span></div>');
                return;
            }
            _homeOpenModal(title, '<div id="homeModalChart" class="home-modal-chart"></div>');
            setTimeout(() => {
                const el = document.getElementById('homeModalChart');
                if (!el) return;
                const chart = echarts.init(el, null, { renderer: 'canvas' });
                HOME_STATE.modalChart = chart;
                // Re-render with the same option; ECharts adapta ao container maior automaticamente
                chart.setOption(option, true);
            }, 30);
        }

        function openHomeGrowthRanking() {
            const ins = HOME_STATE.lastInsights || {};
            const ranking = ins.crescimento_ranking || [];
            const ymAtual = ins.crescimento_ym_atual || '';
            const ymAnterior = ins.crescimento_ym_anterior || '';

            const labelAtual = ymAtual ? _homeFmtMonthLong(ymAtual) : 'Mês atual';
            const labelAnterior = ymAnterior ? _homeFmtMonthLong(ymAnterior) : 'Mês anterior';

            if (!ranking.length) {
                _homeOpenModal('Ranking de Crescimento de Interação', `
                    <div class="home-empty" style="min-height:40vh;">
                        <i class="fas fa-chart-line"></i>
                        <span>Sem dados de comparação entre meses ainda.</span>
                    </div>
                `);
                return;
            }

            const rows = ranking.map((it, i) => {
                let pctCell;
                if (it.is_new) {
                    pctCell = '<span class="home-ranking-pct new">NOVO</span>';
                } else if (it.growth_pct === null || it.growth_pct === undefined) {
                    pctCell = '<span class="home-ranking-pct zero">—</span>';
                } else if (it.growth_pct > 0) {
                    pctCell = `<span class="home-ranking-pct pos">▲ ${it.growth_pct}%</span>`;
                } else if (it.growth_pct < 0) {
                    pctCell = `<span class="home-ranking-pct neg">▼ ${Math.abs(it.growth_pct)}%</span>`;
                } else {
                    pctCell = '<span class="home-ranking-pct zero">= 0%</span>';
                }
                return `<tr>
                    <td class="home-ranking-pos">${i + 1}</td>
                    <td class="home-ranking-name">${escapeHtml(it.name || '-')}</td>
                    <td class="home-ranking-num">${(it.anterior || 0).toLocaleString('pt-BR')}</td>
                    <td class="home-ranking-num">${(it.atual || 0).toLocaleString('pt-BR')}</td>
                    <td>${pctCell}</td>
                </tr>`;
            }).join('');

            const html = `
                <div class="home-ranking-meta">
                    Comparativo entre <b>${escapeHtml(labelAnterior)}</b> e <b>${escapeHtml(labelAtual)}</b> &middot; ${ranking.length} contas com atividade
                </div>
                <div class="home-ranking-scroll">
                    <table class="home-ranking-table">
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>Conta</th>
                                <th style="text-align:right;">${escapeHtml(labelAnterior)}</th>
                                <th style="text-align:right;">${escapeHtml(labelAtual)}</th>
                                <th style="text-align:right;">Variação</th>
                            </tr>
                        </thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            `;
            _homeOpenModal('Ranking de Crescimento de Interação', html);
        }

        function _homeBaseTooltip() {
            return {
                backgroundColor: 'rgba(15, 30, 48, 0.95)',
                borderColor: 'rgba(255,255,255,0.15)',
                borderWidth: 1,
                textStyle: { color: '#e6ecf3', fontSize: 12, fontFamily: 'Geist' },
                extraCssText: 'box-shadow: 0 8px 24px rgba(0,0,0,0.4); border-radius: 8px;',
            };
        }

        function toggleHomePeriodMenu(ev) {
            if (ev) ev.stopPropagation();
            const menu = document.getElementById('homePeriodMenu');
            if (!menu) return;
            menu.classList.toggle('open');
            if (menu.classList.contains('open')) {
                setTimeout(() => {
                    document.addEventListener('click', _homeClosePeriodMenuOutside, { once: true });
                }, 0);
            }
        }
        function _homeClosePeriodMenuOutside(e) {
            const menu = document.getElementById('homePeriodMenu');
            const trigger = document.getElementById('homePeriodTrigger');
            if (!menu) return;
            if (menu.contains(e.target) || trigger.contains(e.target)) {
                document.addEventListener('click', _homeClosePeriodMenuOutside, { once: true });
                return;
            }
            menu.classList.remove('open');
        }
        function toggleHomePeriodAll(checkbox) {
            if (!checkbox.checked) return;
            document.querySelectorAll('.home-month-opt input').forEach(cb => { cb.checked = false; });
        }
        function _homePopulateMonthOptions() {
            const wrap = document.getElementById('homePeriodMonths');
            if (!wrap) return;
            if (!HOME_STATE.availableMonths.length) {
                wrap.innerHTML = '<div style="grid-column:1/-1; padding:8px 6px; font-size:12px; color:var(--hm-text-muted);">Nenhum mês com dados ainda.</div>';
                return;
            }
            wrap.innerHTML = HOME_STATE.availableMonths.map(ym => {
                const checked = HOME_STATE.months.includes(ym);
                return `<label class="home-month-opt"><input type="checkbox" value="${ym}" ${checked ? 'checked' : ''} onchange="_homeOnMonthToggle()"> ${_homeFmtMonthLong(ym)}</label>`;
            }).join('');
        }
        function _homeOnMonthToggle() {
            const any = Array.from(document.querySelectorAll('.home-month-opt input')).some(cb => cb.checked);
            const allCb = document.getElementById('homePeriodAll');
            if (allCb) allCb.checked = !any;
        }
        function applyHomePeriod() {
            const allCb = document.getElementById('homePeriodAll');
            const checked = Array.from(document.querySelectorAll('.home-month-opt input:checked')).map(cb => cb.value);
            if (allCb && allCb.checked || checked.length === 0) {
                HOME_STATE.period = 'all';
                HOME_STATE.months = [];
                document.getElementById('homePeriodLabel').textContent = 'Todo o período';
            } else {
                HOME_STATE.period = 'months';
                HOME_STATE.months = checked.sort();
                const lbl = checked.length === 1 ? _homeFmtMonthLong(checked[0]) : `${checked.length} meses selecionados`;
                document.getElementById('homePeriodLabel').textContent = lbl;
            }
            document.getElementById('homePeriodMenu')?.classList.remove('open');
            loadHome(true);
        }

        function _homeBindResize() {
            if (HOME_STATE.resizeHandlerBound) return;
            HOME_STATE.resizeHandlerBound = true;
            window.addEventListener('resize', () => {
                Object.values(HOME_STATE.charts).forEach(chart => {
                    try { chart?.resize(); } catch (_) {}
                });
                if (HOME_STATE.modalChart) {
                    try { HOME_STATE.modalChart.resize(); } catch (_) {}
                }
            });
        }

        function onHomeFilterChange() {
            HOME_STATE.includeArchived = document.getElementById('homeIncludeArchived')?.checked || false;
            HOME_STATE.includeCold = document.getElementById('homeIncludeCold')?.checked || false;
            loadHome(true);
        }

        async function loadHome(force = false) {
            const tab = document.getElementById('home');
            if (!tab) return;

            // Radar do Dia carrega em paralelo ao dashboard
            if (typeof loadRadarDoDia === 'function') loadRadarDoDia();
            if (typeof loadInboundPending === 'function') loadInboundPending();

            const params = new URLSearchParams();
            params.set('period', HOME_STATE.period);
            if (HOME_STATE.period === 'months' && HOME_STATE.months.length) {
                params.set('months', HOME_STATE.months.join(','));
            }
            params.set('include_archived', HOME_STATE.includeArchived ? '1' : '0');
            params.set('include_cold', HOME_STATE.includeCold ? '1' : '0');

            try {
                const resp = await fetch(`/api/home/overview?${params.toString()}`);
                if (!resp.ok) throw new Error('Falha ao carregar dados');
                const data = await resp.json();

                HOME_STATE.availableMonths = data.meses_disponiveis || [];
                HOME_STATE.lastInsights = data.insights || {};
                _homePopulateMonthOptions();
                _homeInjectCardActions();

                _renderHomeKpis(data.kpis || {});
                _renderHomeUserCard();
                _renderHomeFaturamento(data.top_faturamento || []);
                _renderHomeFaturamentoUnico(data.top_faturamento_unico || []);
                _renderHomeInteracoes(data.top_interacoes || []);
                _renderHomeTargetMenor(data.target_menor_interacao || []);
                _renderHomeCargo(data.interacoes_cargo || []);
                _renderHomeEvolucao(data.evolucao_mensal || []);
                _renderHomeCanal(data.canais || []);
                _renderHomeHeatmap(data.heatmap || []);
                _renderHomeFunil(data.funil || []);
                _renderHomeTempo(data.tempo_sem_contato || []);
                _renderHomeNovos(data.novos_contatos || []);
                _renderHomeInsights(data.insights || {}, data.kpis || {});

                const stamp = document.getElementById('homeUpdateStamp');
                if (stamp) {
                    const now = new Date();
                    stamp.textContent = now.toLocaleDateString('pt-BR') + ' ' + now.toTimeString().slice(0, 5);
                }

                _homeBindResize();
            } catch (e) {
                console.error('[home] erro:', e);
                showError('Erro ao carregar dashboard Home.');
            }
        }

        function _renderHomeKpis(k) {
            const setText = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
            const setFoot = (id, txt, cls = '') => {
                const el = document.getElementById(id);
                if (!el) return;
                el.textContent = txt || '';
                el.className = 'home-kpi-foot' + (cls ? ' ' + cls : '');
            };
            const total = Number(k.total_contacts || 0);
            const pct = n => total > 0 ? ` (${Math.round((Number(n || 0) / total) * 100)}% do total)` : '';
            setText('kpiTotalAccounts', (k.total_accounts || 0).toLocaleString('pt-BR'));
            setFoot('kpiTotalAccountsFoot', '');
            setText('kpiTotalContacts', (k.total_contacts || 0).toLocaleString('pt-BR'));
            setFoot('kpiTotalContactsFoot', '');
            setText('kpiEmDia', (k.em_dia || 0).toLocaleString('pt-BR'));
            setFoot('kpiEmDiaFoot', `${Math.round(((k.em_dia || 0) / Math.max(total, 1)) * 100)}% do total`);
            setText('kpiAtencao', (k.atencao || 0).toLocaleString('pt-BR'));
            setFoot('kpiAtencaoFoot', `${Math.round(((k.atencao || 0) / Math.max(total, 1)) * 100)}% do total`);
            setText('kpiAtrasado', (k.atrasado || 0).toLocaleString('pt-BR'));
            setFoot('kpiAtrasadoFoot', `${Math.round(((k.atrasado || 0) / Math.max(total, 1)) * 100)}% do total`);
            setText('kpiCobertura', `${k.cobertura_pct || 0}%`);
            const meta = 80;
            const cob = Number(k.cobertura_pct || 0);
            const diff = cob - meta;
            const deltaLabel = diff === 0 ? `Meta atingida (${meta}%)` : (diff > 0 ? `${diff} p.p. acima da meta` : `${Math.abs(diff)} p.p. abaixo da meta`);
            setFoot('kpiCoberturaFoot', `${deltaLabel} · últimos 30 dias`, diff < 0 ? 'delta-down' : (diff > 0 ? 'delta-up' : ''));
        }

        function _renderHomeUserCard() {
            const greetingEl = document.getElementById('homeUserGreeting');
            const nameEl = document.getElementById('homeUserName');
            const roleEl = document.getElementById('homeUserRole');
            const avatarEl = document.getElementById('homeUserAvatar');
            if (!greetingEl || !nameEl || !avatarEl) return;

            const profile = (typeof userProfile === 'object' && userProfile) || {};
            // Slot maior (mantém comportamento atual: nickname > full_name)
            const lastNameDisplay = profile.nickname || profile.full_name || 'Visitante';
            // Slot menor: primeiro nome extraído de full_name (apenas quando há ≥2 palavras)
            const parts = (profile.full_name || '').trim().split(/\s+/).filter(Boolean);
            const firstName = parts.length >= 2 ? parts[0] : '';
            const role = profile.position || '';
            const fullName = profile.full_name || profile.nickname || 'Visitante';

            greetingEl.textContent = firstName;
            greetingEl.style.display = firstName ? '' : 'none';
            nameEl.textContent = lastNameDisplay;
            if (roleEl) roleEl.textContent = role;
            nameEl.title = fullName;

            if (profile.photo_url) {
                avatarEl.innerHTML = `<img src="${profile.photo_url}" alt="${escapeHtml(lastNameDisplay)}" onerror="this.parentElement.innerHTML='<span>${escapeHtml((lastNameDisplay || 'U').charAt(0).toUpperCase())}</span>'">`;
            } else {
                avatarEl.innerHTML = `<span>${escapeHtml((lastNameDisplay || 'U').charAt(0).toUpperCase())}</span>`;
            }
        }

        async function openCoberturaDetail() {
            // Cobertura usa janela fixa de 30 dias — sem params de período

            // Garante que o modal existe no DOM (cria uma vez, reutiliza)
            let modal = document.getElementById('coberturaDetailModal');
            if (!modal) {
                modal = document.createElement('div');
                modal.id = 'coberturaDetailModal';
                modal.className = 'coberturaDetailModal';
                modal.setAttribute('role', 'dialog');
                modal.setAttribute('aria-modal', 'true');
                modal.onclick = (e) => { if (e.target === modal) closeCoberturaDetail(); };
                document.body.appendChild(modal);
            }

            modal.innerHTML = `
                <div class="cob-modal-box">
                    <div class="cob-modal-header">
                        <div>
                            <div class="cob-modal-title"><i class="fas fa-bullseye" style="color:#7c3aed;margin-right:7px;"></i>Cobertura de Relacionamento</div>
                            <div class="cob-modal-period" id="cobPeriodLabel">Carregando…</div>
                        </div>
                        <button class="cob-modal-close" onclick="closeCoberturaDetail()" title="Fechar">✕</button>
                    </div>
                    <div class="cob-modal-loading" id="cobModalLoading"><i class="fas fa-spinner fa-spin"></i> Carregando dados…</div>
                    <div id="cobModalContent" style="display:none;">
                        <div class="cob-modal-summary">
                            <div>
                                <div class="cob-modal-pct" id="cobPct">—</div>
                                <div class="cob-modal-pct-label">de cobertura</div>
                            </div>
                            <div class="cob-modal-counts">
                                <div class="cob-modal-count covered">
                                    <div class="cob-modal-count-n" id="cobCoveredCount">—</div>
                                    <div class="cob-modal-count-lbl">com atividade</div>
                                </div>
                                <div class="cob-modal-count" style="color:#9ca3af">
                                    <div class="cob-modal-count-n" style="color:#9ca3af;font-size:22px;font-weight:700;" id="cobTotalCount">—</div>
                                    <div class="cob-modal-count-lbl">total de contas</div>
                                </div>
                                <div class="cob-modal-count uncovered">
                                    <div class="cob-modal-count-n" id="cobUncoveredCount">—</div>
                                    <div class="cob-modal-count-lbl">sem atividade</div>
                                </div>
                            </div>
                        </div>
                        <div class="cob-modal-body">
                            <div>
                                <div class="cob-section-title covered"><i class="fas fa-circle-check"></i> Com atividade (<span id="cobCoveredCountInner">0</span>)</div>
                                <div class="cob-account-list" id="cobCoveredList"></div>
                            </div>
                            <div>
                                <div class="cob-section-title uncovered"><i class="fas fa-circle-xmark"></i> Sem atividade (<span id="cobUncoveredCountInner">0</span>)</div>
                                <div class="cob-account-list" id="cobUncoveredList"></div>
                            </div>
                        </div>
                    </div>
                </div>`;

            modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
            document.removeEventListener('keydown', _coberturaDetailEsc); // evita duplicação
            document.addEventListener('keydown', _coberturaDetailEsc);

            try {
                const resp = await fetch(`/api/home/cobertura-detail`);
                if (!resp.ok) throw new Error('Falha ao carregar dados.');
                const data = await resp.json();

                document.getElementById('cobPeriodLabel').textContent = data.period_label || '';
                document.getElementById('cobPct').textContent = `${data.cobertura_pct || 0}%`;
                document.getElementById('cobCoveredCount').textContent = data.covered_count || 0;
                document.getElementById('cobTotalCount').textContent = data.total || 0;
                document.getElementById('cobUncoveredCount').textContent = (data.total || 0) - (data.covered_count || 0);
                document.getElementById('cobCoveredCountInner').textContent = data.covered_count || 0;
                document.getElementById('cobUncoveredCountInner').textContent = (data.total || 0) - (data.covered_count || 0);

                // Lista de contas COM atividade
                const covEl = document.getElementById('cobCoveredList');
                if (!data.covered?.length) {
                    covEl.innerHTML = '<div class="cob-empty">Nenhuma conta com atividade no período.</div>';
                } else {
                    covEl.innerHTML = data.covered.map(acc => {
                        const lastDt = acc.last_activity ? formatDateBr(acc.last_activity) : '—';
                        const targetBadge = acc.is_target ? '<span class="cob-account-target-badge">⭐ target</span>' : '';
                        return `<div class="cob-account-row${acc.is_target ? ' is-target' : ''}">
                            <span class="cob-account-name" title="${escapeHtml(acc.name || '')}">${escapeHtml(acc.name || '—')}</span>
                            ${targetBadge}
                            <span class="cob-account-count">${acc.activity_count} ativ.</span>
                            <span class="cob-account-meta">último: ${lastDt}</span>
                        </div>`;
                    }).join('');
                }

                // Lista de contas SEM atividade
                const uncovEl = document.getElementById('cobUncoveredList');
                if (!data.uncovered?.length) {
                    uncovEl.innerHTML = '<div class="cob-empty" style="color:#059669;">✅ Todas as contas têm atividade registrada no período!</div>';
                } else {
                    uncovEl.innerHTML = data.uncovered.map(acc => {
                        const targetBadge = acc.is_target ? '<span class="cob-account-target-badge">⭐ target</span>' : '';
                        return `<div class="cob-account-row${acc.is_target ? ' is-target' : ''}">
                            <span class="cob-account-name" title="${escapeHtml(acc.name || '')}">${escapeHtml(acc.name || '—')}</span>
                            ${targetBadge}
                            <span class="cob-account-meta" style="color:#9ca3af;">sem registro</span>
                        </div>`;
                    }).join('');
                }

                document.getElementById('cobModalLoading').style.display = 'none';
                document.getElementById('cobModalContent').style.display = '';
            } catch (e) {
                document.getElementById('cobModalLoading').innerHTML = `<i class="fas fa-circle-exclamation" style="color:#ef4444;"></i> Erro ao carregar: ${escapeHtml(e.message)}`;
            }
        }

        function closeCoberturaDetail() {
            const modal = document.getElementById('coberturaDetailModal');
            if (modal) modal.style.display = 'none';
            document.body.style.overflow = '';
            document.removeEventListener('keydown', _coberturaDetailEsc);
        }
        function _coberturaDetailEsc(e) { if (e.key === 'Escape') closeCoberturaDetail(); }

        // =========================================================
        // HOME — Drill-down genérico (modais de detalhe)
        // =========================================================
        const HD_AVATAR_COLORS = ['#3b82f6','#22d3ee','#a855f7','#ec4899','#f97316','#14b8a6','#22c55e','#eab308'];
        function _hdColor(str) {
            let h = 0; const s = String(str || '?');
            for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
            return HD_AVATAR_COLORS[h % HD_AVATAR_COLORS.length];
        }
        function _hdInitial(name) { return (String(name || '?').trim()[0] || '?').toUpperCase(); }
        function _hdFallbackHtml(name, cls) {
            const fbCls = cls === 'hd-logo' ? 'hd-logo-fallback' : 'hd-avatar-fb';
            return `<div class="${fbCls}" style="background:${_hdColor(name)}">${_hdInitial(name)}</div>`;
        }
        window._hdImgErr = function(img) {
            const name = img.getAttribute('data-name') || '';
            const cls = img.getAttribute('data-cls') || 'hd-avatar';
            img.outerHTML = _hdFallbackHtml(name, cls);
        };
        function _hdLogo(name, url, cls = 'hd-logo') {
            if (url) return `<img class="${cls}" src="${escapeHtml(url)}" alt="" data-name="${escapeHtml(name || '')}" data-cls="${cls}" onerror="_hdImgErr(this)">`;
            return _hdFallbackHtml(name, cls);
        }
        function _hdStatusDot(st) {
            const map = { em_dia: 'green', atencao: 'yellow', atrasado: 'red' };
            return `<span class="hd-dot ${map[st] || 'red'}"></span>`;
        }
        function _hdDays(days) {
            if (days === null || days === undefined) return 'sem contato registrado';
            if (days === 0) return 'hoje';
            return `${days} dia${days === 1 ? '' : 's'} sem contato`;
        }
        function _hdDate(v) { return v ? (typeof formatDateBr === 'function' ? formatDateBr(v) : String(v).slice(0, 10)) : '—'; }

        function _homeChartCursor(id) {
            const el = document.getElementById(id);
            if (el) el.style.cursor = 'pointer';
        }
        function _homeBindBarClick(chart, rows, type, maxlen, axis = 'y') {
            if (!chart) return;
            const fire = (name) => { if (name && type === 'account') openHomeDrill('account', name); };

            // 1) Handlers nativos do ECharts (barra e rótulo do eixo)
            const labelMap = {};
            if (maxlen) rows.forEach(r => { labelMap[_homeShortName(r.name, maxlen)] = r.name; });
            chart.off('click');
            chart.on('click', p => {
                if (p.componentType === 'series') { const r = rows[p.dataIndex]; if (r) fire(r.name); return; }
                if (p.componentType === 'xAxis' || p.componentType === 'yAxis') fire(labelMap[p.value] || p.value);
            });

            // 2) Fallback à prova de falhas: clique em QUALQUER ponto da linha/coluna.
            //    Mapeia o pixel clicado para o índice da categoria via convertFromPixel.
            //    Resolve o problema de barras horizontais finas e cliques no nome.
            const dom = chart.getDom();
            dom.style.cursor = 'pointer';
            dom.onclick = (e) => {
                const rect = dom.getBoundingClientRect();
                const offset = axis === 'y' ? (e.clientY - rect.top) : (e.clientX - rect.left);
                let idx = chart.convertFromPixel({ [axis + 'AxisIndex']: 0 }, offset);
                if (idx === null || idx === undefined || idx < 0) return;
                idx = Math.round(idx);
                const r = rows[idx];
                if (r) fire(r.name);
            };
        }

        function _hdEnsureModal() {
            let modal = document.getElementById('hdModal');
            if (!modal) {
                modal = document.createElement('div');
                modal.id = 'hdModal';
                modal.className = 'hd-modal';
                modal.setAttribute('role', 'dialog');
                modal.setAttribute('aria-modal', 'true');
                modal.onclick = (e) => { if (e.target === modal) closeHomeDrill(); };
                document.body.appendChild(modal);
            }
            return modal;
        }
        function closeHomeDrill() {
            const modal = document.getElementById('hdModal');
            if (modal) modal.style.display = 'none';
            document.body.style.overflow = '';
            document.removeEventListener('keydown', _hdEsc);
        }
        function _hdEsc(e) { if (e.key === 'Escape') closeHomeDrill(); }

        async function openHomeDrill(type, arg) {
            const modal = _hdEnsureModal();
            modal.innerHTML = `<div class="hd-box"><div class="hd-loading"><i class="fas fa-spinner fa-spin"></i> Carregando…</div></div>`;
            modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
            document.removeEventListener('keydown', _hdEsc);
            document.addEventListener('keydown', _hdEsc);

            // monta querystring conforme tipo
            const params = new URLSearchParams({ type });
            if (HOME_STATE.includeArchived) params.set('include_archived', '1');
            if (HOME_STATE.includeCold) params.set('include_cold', '1');
            if (type === 'status') params.set('status', arg);
            else if (type === 'account') params.set('account_name', arg);
            else if (type === 'cargo') params.set('cargo', arg);
            else if (type === 'canal') params.set('canal', arg);
            else if (type === 'evolucao') params.set('ym', arg);

            try {
                const resp = await fetch(`/api/home/drilldown?${params.toString()}`);
                if (!resp.ok) throw new Error('Falha ao carregar dados.');
                const data = await resp.json();
                let html = '';
                if (type === 'accounts') html = _hdRenderAccounts(data);
                else if (type === 'contacts') html = _hdRenderContacts(data);
                else if (type === 'status') html = _hdRenderContacts(data);
                else if (type === 'account') html = _hdRenderAccount(data);
                else if (type === 'cargo') html = _hdRenderCargo(data);
                else if (type === 'canal') html = _hdRenderCanal(data);
                else if (type === 'evolucao') html = _hdRenderEvolucao(data);
                else if (type === 'target_risk') html = _hdRenderTargetRisk(data);
                modal.querySelector('.hd-box').innerHTML = html;
            } catch (e) {
                modal.querySelector('.hd-box').innerHTML =
                    `<div class="hd-loading"><i class="fas fa-circle-exclamation" style="color:#ef4444"></i> Erro: ${escapeHtml(e.message)}</div>`;
            }
        }

        function _hdHeader(iconOrLogo, title, sub) {
            return `<div class="hd-header">
                ${iconOrLogo}
                <div><div class="hd-title">${title}</div><div class="hd-sub">${sub || ''}</div></div>
                <button class="hd-close" onclick="closeHomeDrill()" title="Fechar">✕</button>
            </div>`;
        }

        function _hdRenderAccounts(data) {
            const items = data.items || [];
            const cards = items.map(a => `
                <div class="hd-card clickable" onclick="openHomeDrill('account', ${JSON.stringify(a.name).replace(/"/g, '&quot;')})">
                    ${_hdLogo(a.name, a.logo_url, 'hd-avatar')}
                    <div style="min-width:0;flex:1">
                        <div class="hd-card-name">${escapeHtml(a.name)} ${a.is_target ? '<span class="hd-target">⭐</span>' : ''}</div>
                        <div class="hd-card-meta">${a.contacts} contato${a.contacts === 1 ? '' : 's'}${a.sector ? ' · ' + escapeHtml(a.sector) : ''}</div>
                    </div>
                    <div class="hd-card-num">${a.revenue_cents > 0 ? _homeFmtBRL(a.revenue_cents) : '—'}</div>
                </div>`).join('');
            return _hdHeader(`<div class="hd-logo-fallback" style="background:linear-gradient(135deg,#22d3ee,#3b82f6)"><i class="fas fa-people-group"></i></div>`,
                'Todas as Contas', `${data.count} contas cadastradas`) +
                `<div class="hd-body">${items.length ? `<div class="hd-grid">${cards}</div>` : '<div class="hd-empty">Nenhuma conta cadastrada.</div>'}</div>`;
        }

        function _hdContactCard(c, showCompany = true) {
            const meta = [c.position, showCompany ? c.company : null].filter(Boolean).map(escapeHtml).join(' · ');
            const statusLine = c.status ? `${_hdStatusDot(c.status)}${_hdDays(c.days)}` : '';
            const emailLine = c.email ? `<div class="hd-card-meta" style="margin-top:2px"><i class="fas fa-envelope" style="font-size:10px;opacity:.7"></i> ${escapeHtml(c.email)}</div>` : '';
            return `<div class="hd-card">
                ${_hdLogo(c.name, c.photo_url, 'hd-avatar')}
                <div style="min-width:0;flex:1">
                    <div class="hd-card-name">${escapeHtml(c.name)} ${c.is_target ? '<span class="hd-target">⭐</span>' : ''}</div>
                    <div class="hd-card-meta">${meta || '—'}</div>
                    ${emailLine}
                    ${statusLine ? `<div class="hd-card-meta" style="margin-top:3px">${statusLine}</div>` : ''}
                </div>
                ${c.count !== undefined ? `<div class="hd-card-num">${c.count}<div style="font-size:10px;color:#7c93ad;font-weight:400">interações</div></div>` : ''}
            </div>`;
        }

        function _hdRenderContacts(data) {
            const items = data.items || [];
            const icon = data.status
                ? `<div class="hd-logo-fallback" style="background:${data.status === 'em_dia' ? '#16a34a' : data.status === 'atencao' ? '#ca8a04' : '#dc2626'}"><i class="fas fa-${data.status === 'em_dia' ? 'circle-check' : data.status === 'atencao' ? 'circle-exclamation' : 'triangle-exclamation'}"></i></div>`
                : `<div class="hd-logo-fallback" style="background:linear-gradient(135deg,#3b82f6,#6366f1)"><i class="fas fa-id-card"></i></div>`;
            return _hdHeader(icon, data.title, `${data.count} contato${data.count === 1 ? '' : 's'}`) +
                `<div class="hd-body">${items.length ? `<div class="hd-grid">${items.map(c => _hdContactCard(c)).join('')}</div>` : '<div class="hd-empty">Nenhum contato nesta categoria.</div>'}</div>`;
        }

        function _hdRenderAccount(data) {
            const acc = data.account || {};
            const services = data.services || [];
            const contacts = data.contacts || [];
            const timeline = data.timeline || [];

            const svcHtml = services.length ? services.map(s => `
                <div class="hd-svc-row${s.early_terminated ? ' terminated' : ''}">
                    <div style="min-width:0;flex:1">
                        <div class="hd-svc-name">${escapeHtml(s.name || 'Serviço')}${s.early_terminated ? ' <span style="color:#ef4444;font-size:10px">(encerrado)</span>' : ''}</div>
                        <div class="hd-svc-meta">${[s.owner, s.cell].filter(Boolean).map(escapeHtml).join(' · ') || '—'}</div>
                    </div>
                    <div class="hd-svc-val">${s.revenue_cents ? _homeFmtBRL(s.revenue_cents) : '—'}</div>
                </div>`).join('') : '<div class="hd-empty">Nenhum serviço Stefanini cadastrado.</div>';

            const contactsHtml = contacts.length
                ? `<div class="hd-grid">${contacts.map(c => _hdContactCard(c, false)).join('')}</div>`
                : '<div class="hd-empty">Nenhum contato vinculado.</div>';

            const tlHtml = timeline.length ? timeline.map(t => `
                <div class="hd-tl-row">
                    <span class="hd-tl-chip">${escapeHtml(t.canal || 'Outro')}</span>
                    <div style="min-width:0;flex:1">
                        <div class="hd-tl-info">${escapeHtml(t.info || '(sem descrição)')}</div>
                        <div class="hd-tl-date">${_hdDate(t.dt)}${t.contato ? ' · ' + escapeHtml(t.contato) : ''}</div>
                    </div>
                </div>`).join('') : '<div class="hd-empty">Sem interações registradas.</div>';

            return _hdHeader(_hdLogo(acc.name, acc.logo_url, 'hd-logo'),
                escapeHtml(acc.name) + (acc.is_target ? ' <span class="hd-target">⭐ target</span>' : ''),
                acc.sector || 'Conta') +
                `<div class="hd-body">
                    <div class="hd-stats">
                        <div class="hd-stat"><div class="hd-stat-n">${_homeFmtBRL(data.revenue_active_cents || 0)}</div><div class="hd-stat-l">Receita ativa/mês</div></div>
                        <div class="hd-stat"><div class="hd-stat-n">${services.filter(s => !s.early_terminated).length}</div><div class="hd-stat-l">Serviços ativos</div></div>
                        <div class="hd-stat"><div class="hd-stat-n">${contacts.length}</div><div class="hd-stat-l">Contatos</div></div>
                    </div>
                    <div class="hd-section-title">Serviços Stefanini</div>${svcHtml}
                    <div class="hd-section-title">Contatos da conta</div>${contactsHtml}
                    <div class="hd-section-title">Últimas interações</div>${tlHtml}
                </div>`;
        }

        function _hdRenderCargo(data) {
            const contacts = data.contacts || [];
            const canal = data.canal_breakdown || [];
            const canalPills = canal.map(c => `<span class="hd-pill">${escapeHtml(c.name)} <b>${c.count}</b></span>`).join('') || '<span class="hd-sub">Sem interações.</span>';
            return _hdHeader(`<div class="hd-logo-fallback" style="background:linear-gradient(135deg,#a855f7,#ec4899)"><i class="fas fa-user-tie"></i></div>`,
                data.title, `${data.total_interacoes} interações · ${contacts.length} contatos`) +
                `<div class="hd-body">
                    <div class="hd-section-title">Por canal</div><div>${canalPills}</div>
                    <div class="hd-section-title">Contatos com este cargo</div>
                    ${contacts.length ? `<div class="hd-grid">${contacts.map(c => _hdContactCard(c)).join('')}</div>` : '<div class="hd-empty">Nenhum contato.</div>'}
                </div>`;
        }

        function _hdRenderCanal(data) {
            const accounts = data.accounts || [];
            const contacts = data.contacts || [];
            const accHtml = accounts.length ? accounts.map(a => `
                <div class="hd-card clickable" onclick="openHomeDrill('account', ${JSON.stringify(a.name).replace(/"/g, '&quot;')})">
                    ${_hdLogo(a.name, null, 'hd-avatar')}
                    <div style="min-width:0;flex:1"><div class="hd-card-name">${escapeHtml(a.name)}</div></div>
                    <div class="hd-card-num">${a.count}</div>
                </div>`).join('') : '<div class="hd-empty">—</div>';
            return _hdHeader(`<div class="hd-logo-fallback" style="background:linear-gradient(135deg,#3b82f6,#22d3ee)"><i class="fas fa-comments"></i></div>`,
                data.title, `${data.total} interações por este canal`) +
                `<div class="hd-body">
                    <div class="hd-two">
                        <div><div class="hd-section-title">Top contas por este canal</div>${accHtml}</div>
                        <div><div class="hd-section-title">Contatos alcançados</div>
                            ${contacts.length ? `<div style="display:flex;flex-direction:column;gap:8px">${contacts.map(c => _hdContactCard(c)).join('')}</div>` : '<div class="hd-empty">—</div>'}</div>
                    </div>
                </div>`;
        }

        function _hdRenderEvolucao(data) {
            const accounts = data.accounts || [];
            const canal = data.canal_breakdown || [];
            const delta = data.delta || 0;
            const deltaCls = delta > 0 ? 'hd-delta-up' : (delta < 0 ? 'hd-delta-down' : '');
            const deltaTxt = delta === 0 ? 'sem variação' : `${delta > 0 ? '▲' : '▼'} ${Math.abs(delta)} vs. mês anterior`;
            const canalPills = canal.map(c => `<span class="hd-pill">${escapeHtml(c.name)} <b>${c.count}</b></span>`).join('') || '<span class="hd-sub">—</span>';
            const accHtml = accounts.length ? accounts.map(a => `
                <div class="hd-card clickable" onclick="openHomeDrill('account', ${JSON.stringify(a.name).replace(/"/g, '&quot;')})">
                    ${_hdLogo(a.name, null, 'hd-avatar')}
                    <div style="min-width:0;flex:1"><div class="hd-card-name">${escapeHtml(a.name)}</div></div>
                    <div class="hd-card-num">${a.count}</div>
                </div>`).join('') : '<div class="hd-empty">Nenhuma conta contatada neste mês.</div>';
            return _hdHeader(`<div class="hd-logo-fallback" style="background:linear-gradient(135deg,#22d3ee,#0e7490)"><i class="fas fa-chart-line"></i></div>`,
                data.title, `${_homeFmtMonthLong(data.ym)}`) +
                `<div class="hd-body">
                    <div class="hd-stats">
                        <div class="hd-stat"><div class="hd-stat-n">${data.total}</div><div class="hd-stat-l">Interações no mês</div></div>
                        <div class="hd-stat"><div class="hd-stat-n ${deltaCls}">${deltaTxt}</div><div class="hd-stat-l">Comparativo</div></div>
                    </div>
                    <div class="hd-section-title">Por canal</div><div>${canalPills}</div>
                    <div class="hd-section-title">Contas contatadas</div><div class="hd-grid">${accHtml}</div>
                </div>`;
        }

        function _hdRenderTargetRisk(data) {
            const items = data.items || [];
            const cards = items.map(a => {
                const risco = a.days === null ? 'sem contato registrado' : `${a.days} dias sem contato`;
                return `<div class="hd-card clickable" onclick="openHomeDrill('account', ${JSON.stringify(a.name).replace(/"/g, '&quot;')})">
                    ${_hdLogo(a.name, a.logo_url, 'hd-avatar')}
                    <div style="min-width:0;flex:1">
                        <div class="hd-card-name">${escapeHtml(a.name)} <span class="hd-target">⭐</span></div>
                        <div class="hd-card-meta">${a.contacts} contato${a.contacts === 1 ? '' : 's'}${a.sector ? ' · ' + escapeHtml(a.sector) : ''}</div>
                        <div class="hd-card-meta" style="margin-top:3px"><span class="hd-dot yellow"></span>${risco}</div>
                    </div>
                </div>`;
            }).join('');
            return _hdHeader(`<div class="hd-logo-fallback" style="background:linear-gradient(135deg,#f59e0b,#dc2626)"><i class="fas fa-circle-exclamation"></i></div>`,
                data.title, `${data.count} conta${data.count === 1 ? '' : 's'} target precisando de atenção`) +
                `<div class="hd-body">${items.length
                    ? `<div class="hd-grid">${cards}</div>`
                    : '<div class="hd-empty">🎉 Nenhuma conta target em risco de proximidade.</div>'}</div>`;
        }

        async function exportHomeDashboard() {
            const btn = document.getElementById('homeExportBtn');
            const shell = document.querySelector('#home .home-shell');
            if (!shell) return;
            if (!window.html2canvas) {
                showError('Biblioteca de exportação ainda não carregou. Tente novamente em instantes.');
                return;
            }
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Gerando…</span>';
            }
            try {
                // Espera 1 frame para garantir que o spinner aparece e ECharts renderizou
                await new Promise(r => requestAnimationFrame(r));
                const canvas = await html2canvas(shell, {
                    backgroundColor: '#061121',
                    scale: 2,
                    useCORS: true,
                    allowTaint: false,
                    logging: false,
                    windowWidth: shell.scrollWidth,
                    windowHeight: shell.scrollHeight,
                });
                const link = document.createElement('a');
                const ts = new Date();
                const stamp = `${ts.getFullYear()}-${String(ts.getMonth() + 1).padStart(2, '0')}-${String(ts.getDate()).padStart(2, '0')}_${String(ts.getHours()).padStart(2, '0')}${String(ts.getMinutes()).padStart(2, '0')}`;
                link.download = `toca-home-dashboard_${stamp}.png`;
                link.href = canvas.toDataURL('image/png');
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                if (typeof showInfo === 'function') showInfo('Dashboard exportado com sucesso.');
            } catch (e) {
                console.error('[home export] erro:', e);
                showError('Falha ao exportar dashboard. Veja o console para detalhes.');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fas fa-image"></i><span>Exportar como imagem</span>';
                }
            }
        }

        function _renderHomeFaturamento(rows) {
            if (!rows.length) return _homeRenderEmpty('chartFaturamento', 'Sem dados de faturamento cadastrado');
            const chart = _homeInitChart('chartFaturamento');
            if (!chart) return;
            const reversed = rows.slice().reverse();
            chart.setOption({
                tooltip: { ..._homeBaseTooltip(), formatter: (p) => `<b>${p[0].name}</b><br>${_homeFmtBRL(p[0].value)}` },
                grid: { left: 8, right: 36, top: 8, bottom: 8, containLabel: true },
                xAxis: { type: 'value', axisLabel: { color: '#5e7390', fontSize: 10, formatter: v => _homeFmtBRL(v) }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }, axisLine: { show: false } },
                yAxis: { type: 'category', data: reversed.map(r => _homeShortName(r.name, 14)), axisLabel: { color: '#cbd5e1', fontSize: 11, triggerEvent: true }, axisLine: { show: false }, axisTick: { show: false } },
                series: [{
                    type: 'bar',
                    data: reversed.map(r => r.revenue_cents),
                    itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [{ offset: 0, color: '#1d4ed8' }, { offset: 1, color: '#3b82f6' }]), borderRadius: [0, 4, 4, 0] },
                    barWidth: '60%',
                    label: { show: true, position: 'right', color: '#cbd5e1', fontSize: 10, formatter: p => _homeFmtBRL(p.value) },
                }],
            });
            _homeBindBarClick(chart, reversed, 'account', 14, 'y');
        }

        function _renderHomeFaturamentoUnico(rows) {
            if (!rows.length) return _homeRenderEmpty('chartFaturamentoUnico', 'Sem dados de faturamento único cadastrado');
            const chart = _homeInitChart('chartFaturamentoUnico');
            if (!chart) return;
            const reversed = rows.slice().reverse();
            chart.setOption({
                tooltip: { ..._homeBaseTooltip(), formatter: (p) => `<b>${p[0].name}</b><br>${_homeFmtBRL(p[0].value)}` },
                grid: { left: 8, right: 36, top: 8, bottom: 8, containLabel: true },
                xAxis: { type: 'value', axisLabel: { color: '#5e7390', fontSize: 10, formatter: v => _homeFmtBRL(v) }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }, axisLine: { show: false } },
                yAxis: { type: 'category', data: reversed.map(r => _homeShortName(r.name, 14)), axisLabel: { color: '#cbd5e1', fontSize: 11, triggerEvent: true }, axisLine: { show: false }, axisTick: { show: false } },
                series: [{
                    type: 'bar',
                    data: reversed.map(r => r.revenue_cents),
                    itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [{ offset: 0, color: '#0f766e' }, { offset: 1, color: '#2dd4bf' }]), borderRadius: [0, 4, 4, 0] },
                    barWidth: '60%',
                    label: { show: true, position: 'right', color: '#cbd5e1', fontSize: 10, formatter: p => _homeFmtBRL(p.value) },
                }],
            });
            _homeBindBarClick(chart, reversed, 'account', 14, 'y');
        }

        function _renderHomeInteracoes(rows) {
            if (!rows.length) return _homeRenderEmpty('chartInteracoes', 'Nenhuma interação registrada');
            const chart = _homeInitChart('chartInteracoes');
            if (!chart) return;
            chart.setOption({
                tooltip: { ..._homeBaseTooltip(), trigger: 'axis', axisPointer: { type: 'shadow' } },
                grid: { left: 8, right: 8, top: 28, bottom: 32, containLabel: true },
                xAxis: { type: 'category', data: rows.map(r => _homeShortName(r.name, 9)), axisLabel: { color: '#cbd5e1', fontSize: 10, interval: 0, rotate: 35, triggerEvent: true }, axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } }, axisTick: { show: false } },
                yAxis: { type: 'value', axisLabel: { color: '#5e7390', fontSize: 10 }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }, axisLine: { show: false } },
                series: [{
                    type: 'bar',
                    data: rows.map(r => r.count),
                    itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: '#22d3ee' }, { offset: 1, color: '#0e7490' }]), borderRadius: [4, 4, 0, 0] },
                    barWidth: '55%',
                    label: { show: true, position: 'top', color: '#cbd5e1', fontSize: 10 },
                }],
            });
            _homeBindBarClick(chart, rows, 'account', 9, 'x');
        }

        function _renderHomeTargetMenor(rows) {
            if (!rows.length) return _homeRenderEmpty('chartTargetMenor', 'Nenhuma conta target cadastrada');
            const chart = _homeInitChart('chartTargetMenor');
            if (!chart) return;
            chart.setOption({
                tooltip: _homeBaseTooltip(),
                grid: { left: 8, right: 70, top: 8, bottom: 8, containLabel: true },
                xAxis: { type: 'value', axisLabel: { color: '#5e7390', fontSize: 10 }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }, axisLine: { show: false } },
                yAxis: { type: 'category', data: rows.map(r => _homeShortName(r.name, 16)).reverse(), axisLabel: { color: '#fca5a5', fontSize: 11, triggerEvent: true }, axisLine: { show: false }, axisTick: { show: false } },
                series: [{
                    type: 'bar',
                    data: rows.slice().reverse().map(r => r.count),
                    itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [{ offset: 0, color: '#7f1d1d' }, { offset: 1, color: '#ef4444' }]), borderRadius: [0, 4, 4, 0] },
                    barWidth: '55%',
                    label: {
                        show: true,
                        position: 'right',
                        color: '#fca5a5',
                        fontSize: 11,
                        fontWeight: 700,
                        formatter: p => `${p.value}   ☹  △`,
                    },
                }],
            });
            _homeBindBarClick(chart, rows.slice().reverse(), 'account', 16, 'y');
        }

        function _renderHomeCargo(rows) {
            if (!rows.length) return _homeRenderEmpty('chartCargo', 'Nenhuma interação por cargo');
            const chart = _homeInitChart('chartCargo');
            if (!chart) return;
            const total = rows.reduce((a, b) => a + (b.count || 0), 0);
            chart.setOption({
                color: HOME_PALETTE,
                tooltip: { ..._homeBaseTooltip(), trigger: 'item', formatter: p => `<b>${p.name}</b><br>${p.value} interações (${p.percent}%)` },
                legend: { orient: 'vertical', right: 0, top: 'middle', textStyle: { color: '#cbd5e1', fontSize: 11 }, itemWidth: 10, itemHeight: 10, icon: 'circle' },
                series: [{
                    type: 'pie',
                    radius: ['55%', '78%'],
                    center: ['32%', '50%'],
                    avoidLabelOverlap: true,
                    itemStyle: { borderRadius: 4, borderColor: '#0f1e30', borderWidth: 2 },
                    label: { show: true, position: 'inside', color: '#fff', fontSize: 10, fontWeight: 700, formatter: p => p.percent >= 6 ? `${p.percent}%` : '' },
                    labelLine: { show: false },
                    data: rows.map(r => ({ name: r.name, value: r.count })),
                }],
                graphic: [{
                    type: 'text',
                    left: '32%',
                    top: '46%',
                    style: { text: total.toLocaleString('pt-BR'), fill: '#fff', fontSize: 18, fontWeight: 700, textAlign: 'center' },
                }, {
                    type: 'text',
                    left: '32%',
                    top: '58%',
                    style: { text: 'Total', fill: '#8aa0b8', fontSize: 11, textAlign: 'center' },
                }],
            });
            chart.off('click');
            chart.on('click', p => { if (p.name) openHomeDrill('cargo', p.name); });
            _homeChartCursor('chartCargo');
        }

        function _renderHomeEvolucao(rows) {
            if (!rows.length || !rows.some(r => r.count > 0)) return _homeRenderEmpty('chartEvolucao', 'Sem evolução para exibir');
            const chart = _homeInitChart('chartEvolucao');
            if (!chart) return;
            chart.setOption({
                tooltip: { ..._homeBaseTooltip(), trigger: 'axis', formatter: p => `<b>${_homeFmtMonthLong(p[0].name)}</b><br>${p[0].value} interações` },
                grid: { left: 8, right: 16, top: 24, bottom: 28, containLabel: true },
                xAxis: { type: 'category', boundaryGap: false, data: rows.map(r => r.ym), axisLabel: { color: '#5e7390', fontSize: 10, formatter: _homeFmtMonthLabel }, axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } }, axisTick: { show: false } },
                yAxis: { type: 'value', axisLabel: { color: '#5e7390', fontSize: 10 }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }, axisLine: { show: false } },
                series: [{
                    type: 'line',
                    smooth: true,
                    symbol: 'circle',
                    symbolSize: 7,
                    lineStyle: { width: 2.5, color: '#22d3ee' },
                    itemStyle: { color: '#22d3ee', borderColor: '#0f1e30', borderWidth: 2 },
                    areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(34,211,238,0.35)' }, { offset: 1, color: 'rgba(34,211,238,0)' }]) },
                    label: { show: true, position: 'top', color: '#cbd5e1', fontSize: 10 },
                    data: rows.map(r => r.count),
                }],
            });
            chart.off('click');
            chart.on('click', p => { const r = rows[p.dataIndex]; if (r) openHomeDrill('evolucao', r.ym); });
            _homeChartCursor('chartEvolucao');
        }

        function _renderHomeCanal(rows) {
            if (!rows.length) return _homeRenderEmpty('chartCanal', 'Sem canais registrados');
            const chart = _homeInitChart('chartCanal');
            if (!chart) return;
            chart.setOption({
                color: ['#3b82f6', '#22d3ee', '#22c55e', '#facc15', '#a855f7', '#ec4899'],
                tooltip: { ..._homeBaseTooltip(), trigger: 'item', formatter: p => `<b>${p.name}</b><br>${p.value} contatos (${p.percent}%)` },
                legend: { orient: 'vertical', right: 0, top: 'middle', textStyle: { color: '#cbd5e1', fontSize: 11 }, itemWidth: 10, itemHeight: 10, icon: 'circle' },
                series: [{
                    type: 'pie',
                    radius: ['55%', '78%'],
                    center: ['32%', '50%'],
                    itemStyle: { borderRadius: 4, borderColor: '#0f1e30', borderWidth: 2 },
                    label: { show: true, position: 'inside', color: '#fff', fontSize: 10, fontWeight: 700, formatter: p => p.percent >= 6 ? `${p.percent}%` : '' },
                    labelLine: { show: false },
                    data: rows.map(r => ({ name: r.name, value: r.count })),
                }],
                graphic: [{
                    type: 'text',
                    left: '32%',
                    top: '48%',
                    style: { text: '💬', fontSize: 20, textAlign: 'center' },
                }],
            });
            chart.off('click');
            chart.on('click', p => { if (p.name) openHomeDrill('canal', p.name); });
            _homeChartCursor('chartCanal');
        }

        function _renderHomeHeatmap(rows) {
            const periodos = ['Manhã', 'Tarde', 'Noite'];
            const diasIdx = [1, 2, 3, 4, 5, 6, 0]; // Seg..Dom
            const diasLabel = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];
            const data = [];
            let max = 0;
            diasIdx.forEach((dow, dx) => {
                periodos.forEach((per, py) => {
                    const found = rows.find(r => Number(r.dow) === dow && r.periodo === per);
                    const v = found ? found.count : 0;
                    if (v > max) max = v;
                    data.push([dx, py, v]);
                });
            });
            if (max === 0) return _homeRenderEmpty('chartHeatmap', 'Sem registros de atividade');
            const chart = _homeInitChart('chartHeatmap');
            if (!chart) return;
            chart.setOption({
                tooltip: { ..._homeBaseTooltip(), formatter: p => `${diasLabel[p.value[0]]} • ${periodos[p.value[1]]}<br><b>${p.value[2]}</b> interações` },
                grid: { left: 40, right: 8, top: 16, bottom: 24 },
                xAxis: { type: 'category', data: diasLabel, splitArea: { show: false }, axisLabel: { color: '#cbd5e1', fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false } },
                yAxis: { type: 'category', data: periodos, splitArea: { show: false }, axisLabel: { color: '#cbd5e1', fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false } },
                visualMap: { show: false, min: 0, max: max, inRange: { color: ['rgba(34,211,238,0.06)', 'rgba(34,211,238,0.4)', '#22d3ee'] } },
                series: [{ type: 'heatmap', data, itemStyle: { borderRadius: 4, borderColor: '#0f1e30', borderWidth: 2 }, emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(34,211,238,0.6)' } } }],
            });
        }

        function _renderHomeFunil(rows) {
            if (!rows.length || rows.every(r => r.count === 0)) return _homeRenderEmpty('chartFunil', 'Sem dados de funil');
            const chart = _homeInitChart('chartFunil');
            if (!chart) return;
            const top = rows[0]?.count || 1;
            const colors = ['#3b82f6', '#22d3ee', '#22c55e', '#facc15', '#ef4444'];
            chart.setOption({
                tooltip: { ..._homeBaseTooltip(), formatter: p => `<b>${p.name}</b><br>${p.value} (${Math.round((p.value / top) * 100)}%)` },
                series: [{
                    type: 'funnel',
                    left: 0,
                    top: 8,
                    bottom: 8,
                    width: '100%',
                    sort: 'descending',
                    gap: 2,
                    label: {
                        show: true,
                        position: 'inside',
                        color: '#fff',
                        fontSize: 11,
                        fontWeight: 600,
                        formatter: p => `${p.name}: ${p.value} (${Math.round((p.value / top) * 100)}%)`,
                    },
                    itemStyle: { borderColor: '#0f1e30', borderWidth: 1 },
                    data: rows.map((r, i) => ({ name: r.label, value: r.count, itemStyle: { color: colors[i % colors.length] } })),
                }],
            });
        }

        function _renderHomeTempo(rows) {
            if (!rows.length || rows.every(r => r.count === 0)) return _homeRenderEmpty('chartTempo', 'Sem dados de tempo sem contato');
            const chart = _homeInitChart('chartTempo');
            if (!chart) return;
            const labels = ['0 - 7 dias', '8 - 14 dias', '15 - 30 dias', '+ 30 dias'];
            const colors = ['#22c55e', '#facc15', '#f97316', '#ef4444'];
            chart.setOption({
                tooltip: { ..._homeBaseTooltip() },
                grid: { left: 8, right: 28, top: 8, bottom: 8, containLabel: true },
                xAxis: { type: 'value', axisLabel: { color: '#5e7390', fontSize: 10 }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }, axisLine: { show: false } },
                yAxis: { type: 'category', data: labels, axisLabel: { color: '#cbd5e1', fontSize: 11 }, axisLine: { show: false }, axisTick: { show: false } },
                series: [{
                    type: 'bar',
                    data: rows.map((r, i) => ({ value: r.count, itemStyle: { color: colors[i], borderRadius: [0, 4, 4, 0] } })),
                    barWidth: '65%',
                    label: { show: true, position: 'right', color: '#cbd5e1', fontSize: 11, fontWeight: 600 },
                }],
            });
        }

        function _renderHomeNovos(rows) {
            if (!rows.length || rows.every(r => r.count === 0)) return _homeRenderEmpty('chartNovos', 'Sem novos contatos no histórico');
            const chart = _homeInitChart('chartNovos');
            if (!chart) return;
            chart.setOption({
                tooltip: { ..._homeBaseTooltip(), trigger: 'axis', formatter: p => `<b>${_homeFmtMonthLong(p[0].name)}</b><br>${p[0].value} novos contatos` },
                grid: { left: 8, right: 8, top: 24, bottom: 22, containLabel: true },
                xAxis: { type: 'category', data: rows.map(r => r.ym), axisLabel: { color: '#5e7390', fontSize: 9, formatter: _homeFmtMonthLabel }, axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } }, axisTick: { show: false } },
                yAxis: { type: 'value', axisLabel: { color: '#5e7390', fontSize: 10 }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }, axisLine: { show: false } },
                series: [{
                    type: 'bar',
                    data: rows.map(r => r.count),
                    itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: '#a855f7' }, { offset: 1, color: '#6d28d9' }]), borderRadius: [4, 4, 0, 0] },
                    barWidth: '55%',
                    label: { show: true, position: 'top', color: '#cbd5e1', fontSize: 9 },
                }],
            });
        }

        function _renderHomeInsights(ins, kpis) {
            const setTxt = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
            setTxt('insTargetCount', ins.target_sem_contato_20d || 0);
            setTxt('insRiscoCount', ins.target_em_risco || 0);
            setTxt('insCobAtual', `${kpis.cobertura_pct || 0}%`);

            const growthList = document.getElementById('insGrowthList');
            if (growthList) {
                const items = (ins.crescimento_top || []);
                if (!items.length) {
                    growthList.innerHTML = '<div style="font-size:12px; color:var(--hm-text-dim);">Sem crescimento expressivo no mês.</div>';
                } else {
                    growthList.innerHTML = items.map(it => `
                        <div class="ins-item">
                            <span class="ins-item-name">${escapeHtml(_homeShortName(it.name, 22))}</span>
                            <span class="ins-item-val">▲ ${it.growth_pct}%</span>
                        </div>`).join('');
                }
            }
        }

        // Renderiza apenas a barra de filtros no container dedicado.
        // Chamada por loadDashboard() e clearDashboardFilters().
        function _renderDashboardFilters() {
            const container = document.getElementById('dashboardFiltersContainer');
            if (!container) return;
            container.innerHTML = renderFilters('Dashboard', clients, dashboardCompanyFilter, dashboardPositionFilter);
        }

        // Renderiza apenas a tabela de contatos no container dedicado, usando os dados já
        // em memória. Não faz fetch — é chamada diretamente por filtros e busca para que o
        // input de pesquisa nunca seja destruído (evita perda de foco durante a digitação).
        function _renderDashboardTable() {
            const container = document.getElementById('dashboardTableContainer');
            if (!container) return;

            if (!clients || clients.length === 0) {
                container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🐰</div><h3>Nenhum cliente cadastrado</h3><p>Comece cadastrando seus clientes para acompanhar o relacionamento com eles.</p><button class="btn btn-primary" onclick="switchTab(null, \'clientes\')"><i class="fas fa-plus"></i> Cadastrar Cliente</button></div>';
                return;
            }

            const contactSearchTerm = (dashboardContactSearch || '').trim().toLocaleLowerCase('pt-BR');
            let filteredClients = clients.filter(client => {
                const byCompany = !dashboardCompanyFilter || (client.company || '') === dashboardCompanyFilter;
                const byPosition = !dashboardPositionFilter || (client.position || '') === dashboardPositionFilter;
                const byTarget = !dashboardTargetFilter || (dashboardTargetFilter === 'target' ? Number(client.is_target) === 1 : Number(client.is_target) !== 1);
                const byContact = !contactSearchTerm || String(client.name || '').toLocaleLowerCase('pt-BR').includes(contactSearchTerm);
                return byCompany && byPosition && byTarget && byContact;
            });

            const sortedClients = sortClients(filteredClients, dashboardSortField, dashboardSortOrder);
            const activeClients = sortedClients.filter(client => !isArchivedClient(client));
            const archivedClients = sortedClients.filter(client => isArchivedClient(client));

            let html = '<div class="dashboard-scroll-wrapper"><div class="table-container"><table class="dashboard-table"><thead><tr>';
            html += '<th style="min-width:50px;"></th>';
            html += '<th onclick="toggleDashboardSort(\'name\')" style="cursor: pointer; min-width: 120px;">Contato <i class="fas fa-sort" style="opacity: 0.5; margin-left: 5px;"></i></th>';
            html += '<th onclick="toggleDashboardSort(\'company\')" style="cursor: pointer; min-width: 130px;">Conta <i class="fas fa-sort" style="opacity: 0.5; margin-left: 5px;"></i></th>';
            html += '<th onclick="toggleDashboardSort(\'position\')" style="cursor: pointer; min-width: 110px; white-space: nowrap;">Cargo <i class="fas fa-sort" style="opacity: 0.5; margin-left: 5px;"></i></th>';
            html += '<th onclick="toggleDashboardSort(\'email\')" style="cursor: pointer; min-width: 140px; white-space: nowrap;">Email <i class="fas fa-sort" style="opacity: 0.5; margin-left: 5px;"></i></th>';
            html += '<th onclick="toggleDashboardSort(\'phone\')" style="cursor: pointer; min-width: 120px; white-space: nowrap;">Telefone <i class="fas fa-sort" style="opacity: 0.5; margin-left: 5px;"></i></th>';
            html += '<th class="th-last-contact" onclick="toggleDashboardSort(\'last_activity_date\')" style="cursor: pointer; min-width: 110px; white-space: nowrap;">Último Contato <i class="fas fa-sort" style="opacity: 0.5; margin-left: 5px;"></i></th>';
            html += '<th onclick="toggleDashboardSort(\'status\')" style="cursor: pointer; min-width: 100px; white-space: nowrap;">Status <i class="fas fa-sort" style="opacity: 0.5; margin-left: 5px;"></i></th>';
            html += '<th style="min-width: 110px; text-align: center; white-space: nowrap;">Ação</th>';
            html += '</tr></thead><tbody>';

            const renderRow = (client, { isArchived = false } = {}) => {
                const status = getStatus(client.last_activity_date, client.position, client.is_target, client.is_cold_contact);
                const statusClass = `status-${status}`;
                const statusText = status === 'green' ? 'Em dia' : status === 'yellow' ? 'Atenção' : 'Atrasado';
                const avatarBase = client.photo_url ? `<img src="${client.photo_url}" class="client-avatar with-photo">` : `<div class="client-avatar">${client.name.charAt(0).toUpperCase()}</div>`;
                const avatar = `<div style="position:relative; display:inline-block;">${avatarBase}${Number(client.is_cold_contact)===1?'<span class="snowflake-badge">❄</span>':''}</div>`;
                const companyCell = isArchived
                    ? '<span style="color:#9ca3af;">(Arquivado)</span>'
                    : `<button class="table-link-btn" onclick="openGroupModalFromEncoded('company', '${encodeURIComponent(client.company || '')}')">${client.company}</button>`;
                html += `<tr class="${isArchived ? 'archived-contact-row' : ''}">
                    <td>${avatar}</td>
                    <td><button class="table-link-btn" onclick="closeGroupModal(); openProfileModal(${client.id})">${client.name}</button></td>
                    <td style="min-width:142px;">${companyCell}</td>
                    <td style="white-space: nowrap;"><button class="table-link-btn" onclick="openGroupModalFromEncoded('position', '${encodeURIComponent(client.position || '')}')">${client.position}</button></td>
                    <td class="small-col-text" style="white-space: nowrap;">${client.email || '-'}</td>
                    <td class="small-col-text" style="white-space: nowrap;">${formatPhone(client.phone) || '-'}</td>
                    <td class="last-contact-text">${client.last_activity_date ? new Date(client.last_activity_date).toLocaleDateString('pt-BR') : '-'}</td>
                    <td style="white-space: nowrap;">${isArchived ? '<span style="color:#9ca3af;">Arquivado</span>' : `<span class="status-badge ${statusClass}"><i class="fas fa-circle"></i> ${statusText}</span>`}</td>
                    <td style="text-align: center;">
                        <div class="action-buttons">
                            ${isArchived
                                ? `<button class="btn-icon-action" onclick="unarchiveClient(${client.id})" title="Desarquivar Contato"><i class="fas fa-box-open"></i></button>`
                                : `<button class="btn-icon-action" onclick="openQuickActivityModal(${client.id}, '${escapeHtml(client.name)}', '${escapeHtml(client.company)}')" title="Adicionar Atividade"><i class="fas fa-plus-circle"></i></button>
                            <button class="btn-icon-action" onclick="openWhatsAppMessageModal(${client.id})" title="Enviar mensagem no WhatsApp"><i class="fab fa-whatsapp"></i></button>
                            <button class="btn-icon-action" onclick="openEmailDraftModal(${client.id})" title="Criar e-mail no Outlook"><i class="fas fa-envelope"></i></button>`}
                        </div>
                    </td>
                </tr>`;
            };

            activeClients.forEach(client => renderRow(client));
            html += `<tr class="dashboard-archived-header" onclick="toggleDashboardArchivedSection()"><td colspan="9"><div style="display:flex; justify-content:space-between; align-items:center;"><span>Contatos Arquivados (${archivedClients.length})</span><span>${dashboardArchivedExpanded ? '▾' : '▸'}</span></div></td></tr>`;
            if (dashboardArchivedExpanded) {
                archivedClients.forEach(client => renderRow(client, { isArchived: true }));
            }
            html += '</tbody></table></div></div>';

            container.innerHTML = html;
        }

        async function loadDashboard() {
            try {
                const response = await fetch(`${API_BASE}/clientes`);
                const data = await response.json();
                clients = data;
                await renderDashboardGreeting();
                await updateWeekCommitmentsBell();

                // Inicializa os dois containers separados na primeira carga.
                // A barra de filtros (#dashboardFiltersContainer) persiste entre re-renders
                // de tabela, garantindo que o input de pesquisa nunca perca o foco.
                const content = document.getElementById('dashboardContent');
                if (!document.getElementById('dashboardFiltersContainer')) {
                    content.innerHTML = '<div id="dashboardFiltersContainer"></div><div id="dashboardTableContainer"></div>';
                }

                _renderDashboardFilters();
                _renderDashboardTable();

                await updateWeekCommitmentsBell();
            } catch (error) {
                showError('Erro ao carregar dashboard');
            }
        }

        // Load Clients
        async function loadClients() {
            try {
                const response = await fetch(`${API_BASE}/clientes`);
                const data = await response.json();
                clients = data;
                await renderDashboardGreeting();

                let html = '';
                if (clients.length === 0) {
                    html = '<div class="empty-state"><div class="empty-state-icon">📋</div><h3>Nenhum cliente cadastrado</h3><p>Clique em "Novo Cliente" para começar.</p></div>';
                } else {
                    let filteredClients = clients.filter(client => {
                        const byCompany = !clientsCompanyFilter || (client.company || '') === clientsCompanyFilter;
                        const byPosition = !clientsPositionFilter || (client.position || '') === clientsPositionFilter;
                        const byName = !clientsNameSearch || String(client.name || '').toLowerCase().includes(clientsNameSearch.toLowerCase());
                        return byCompany && byPosition && byName;
                    });

                    const sortedClients = sortClients(filteredClients, clientsSortField, clientsSortOrder);

                    html += renderFilters('Clients', clients, clientsCompanyFilter, clientsPositionFilter);
                    html += '<div class="table-container"><table><thead><tr>';
                    html += '<th></th>';
                    html += '<th onclick="toggleClientsSort(\'name\')" style="cursor: pointer;">Contato <i class="fas fa-sort" style="opacity: 0.5; margin-left: 5px;"></i></th>';
                    html += '<th onclick="toggleClientsSort(\'company\')" style="cursor: pointer;">Conta <i class="fas fa-sort" style="opacity: 0.5; margin-left: 5px;"></i></th>';
                    html += '<th onclick="toggleClientsSort(\'position\')" style="cursor: pointer;">Cargo <i class="fas fa-sort" style="opacity: 0.5; margin-left: 5px;"></i></th>';
                    html += '<th class="clients-email-col" onclick="toggleClientsSort(\'email\')" style="cursor: pointer;">Email <i class="fas fa-sort" style="opacity: 0.5; margin-left: 5px;"></i></th>';
                    html += '<th>Área de Atuação</th>';
                    html += '<th onclick="toggleClientsSort(\'phone\')" style="cursor: pointer;">Telefone <i class="fas fa-sort" style="opacity: 0.5; margin-left: 5px;"></i></th>';
                    html += '<th>Ações</th>';
                    html += '</tr></thead><tbody>';

                    sortedClients.forEach(client => {
                        const archived = isArchivedClient(client);
                        const avatarBase = client.photo_url ? `<img src="${client.photo_url}" class="client-avatar with-photo">` : `<div class="client-avatar">${client.name.charAt(0).toUpperCase()}</div>`;
                        const avatar = `<div style="position:relative; display:inline-block;">${avatarBase}${Number(client.is_cold_contact)===1?'<span class="snowflake-badge">❄</span>':''}</div>`;
                        html += `<tr class="${archived ? 'archived-contact-row' : ''}">
                            <td>${avatar}</td>
                            <td><button class="table-link-btn" onclick="closeGroupModal(); openProfileModal(${client.id})">${client.name}</button></td>
                            <td style="min-width:200px;">${archived ? '<span style="color:#9ca3af;">(Arquivado)</span>' : `<button class="table-link-btn" onclick="openGroupModalFromEncoded('company', '${encodeURIComponent(client.company || '')}')">${client.company}</button>`}</td>
                            <td><button class="table-link-btn" onclick="openGroupModalFromEncoded('position', '${encodeURIComponent(client.position || '')}')">${client.position}</button></td>
                            <td class="clients-email-col">${client.email || '-'}</td>
                            <td class="small-col-text">${client.area_of_activity || '-'}</td>
                            <td class="small-col-text">${formatPhone(client.phone) || '-'}</td>
                            <td><div class="actions">
                                <button class="btn btn-edit-accent btn-small" onclick="editClient(${client.id})"><i class="fas fa-edit"></i> Editar</button>
                                <button class="btn btn-danger btn-small" onclick="deleteClient(${client.id})"><i class="fas fa-trash"></i> Deletar</button>
                            </div></td>
                        </tr>`;
                    });
                    html += '</tbody></table></div>';
                }

                document.getElementById('clientsList').innerHTML = html;
            } catch (error) {
                showError('Erro ao carregar clientes');
            }
        }

        // Load Activities
        async function loadActivities() {
            try {
                const response = await fetch(`${API_BASE}/atividades`);
                const data = await response.json();
                activities = data;

                let html = '';
                if (activities.length === 0) {
                    html = '<div class="empty-state"><div class="empty-state-icon">📝</div><h3>Nenhuma atividade registrada</h3><p>Clique em "Nova Atividade" para começar.</p></div>';
                } else {
                    html = '<div class="table-container"><table><thead><tr>';
                    html += '<th class="small-col-text">Cliente</th><th class="small-col-text">Tipo</th><th class="small-col-text">Informações</th><th class="small-col-text">Data</th><th>Ações</th>';
                    html += '</tr></thead><tbody>';

                    activities.forEach(activity => {
                        const date = new Date(activity.activity_date || activity.created_at).toLocaleDateString('pt-BR');
                        const contactType = activity.contact_type || 'Outro';
                        const information = activity.information || '-';
                        html += `<tr>
                            <td class='small-col-text'>${activity.name}</td>
                            <td class='small-col-text'>${contactType}</td>
                            <td class='small-col-text'>${information}</td>
                            <td class='small-col-text'>${date}</td>
                            <td><div class="actions">
                                <button class="btn btn-secondary btn-small" onclick="editActivity(${activity.id})"><i class="fas fa-edit"></i> Editar</button>
                                <button class="btn btn-danger btn-small" onclick="deleteActivity(${activity.id})"><i class="fas fa-trash"></i> Deletar</button>
                            </div></td>
                        </tr>`;
                    });
                    html += '</tbody></table></div>';
                }

                document.getElementById('activitiesList').innerHTML = html;
            } catch (error) {
                showError('Erro ao carregar atividades');
            }
        }

        // Load Reports
        async function loadReports() {
            try {
                const accountsResponse = await fetch(`${API_BASE}/accounts`);
                const accountsData = await accountsResponse.json();
                const response = await fetch(`${API_BASE}/clientes`);
                const data = await response.json();
                clients = data;

                let html = '<div class="relreport-hero" style="background: linear-gradient(135deg, rgba(4,120,87,0.96), rgba(6,95,70,0.96)); color: white; padding: 24px; border-radius: 16px; box-shadow: 0 14px 40px rgba(4,120,87,0.16);">';
                html += '<div style="max-width:680px;">';
                html += '<h2 style="margin:0 0 8px 0; font-size:28px; font-weight:700;">Relationship Report</h2>';
                html += '<p style="margin:0; font-size:14px; line-height:1.6; color:rgba(255,255,255,0.92);">Abra um report executivo visual no navegador com identidade da conta, foto do usuário, cards dos contatos, contexto relacional, leitura temática e botão para imprimir ou salvar em PDF.</p>';
                html += '</div></div>';

                html += '<div style="background: rgba(255,255,255,0.92); padding: 22px; border-radius: 16px; border: 1px solid rgba(52,211,153,0.24); box-shadow: 0 12px 34px rgba(15,23,42,0.05); margin-top:20px;">';
                html += '<div style="display:flex; justify-content:space-between; align-items:flex-start; gap:16px; margin-bottom:18px; flex-wrap:wrap;">';
                html += '<div><h3 style="color:#047857; margin:0 0 6px 0;">Gerar Relationship Report</h3><p style="color:#6b7280; margin:0; font-size:14px;">Selecione a conta e o período para montar o PDF completo.</p></div>';
                html += '<div style="background:#ecfdf5; color:#065f46; border:1px solid #a7f3d0; border-radius:999px; padding:8px 12px; font-size:12px; font-weight:600;">Resumo com IA incluído</div>';
                html += '</div>';
                html += '<div class="form-group" style="margin-bottom:14px;">';
                html += '<label style="display:block; margin-bottom:8px; font-weight:600; color:#065f46;">Cliente / Conta</label>';
                html += '<select id="relationReportAccount" style="width:100%; border:2px solid #d1fae5; padding:12px; border-radius:10px; background:white;">';
                html += '<option value="">Selecione uma conta</option>';
                (Array.isArray(accountsData) ? accountsData : []).forEach(account => {
                    html += `<option value="${account.id}">${escapeHtml(account.name || 'Conta sem nome')}</option>`;
                });
                html += '</select>';
                html += '</div>';
                html += '<div style="display:grid; grid-template-columns:1fr 1fr; gap:14px;">';
                html += '<div class="form-group">';
                html += '<label style="display:block; margin-bottom:8px; font-weight:600; color:#065f46;">Data Inicial</label>';
                html += '<input type="date" id="relationReportStart" style="width:100%; border:2px solid #e5e7eb; padding:12px; border-radius:10px; background:white;">';
                html += '</div>';
                html += '<div class="form-group">';
                html += '<label style="display:block; margin-bottom:8px; font-weight:600; color:#065f46;">Data Final</label>';
                html += '<input type="date" id="relationReportEnd" style="width:100%; border:2px solid #e5e7eb; padding:12px; border-radius:10px; background:white;">';
                html += '</div>';
                html += '</div>';
                html += '<div style="margin-top:12px; display:flex; align-items:center; gap:10px; flex-wrap:wrap;">';
                html += '<label style="display:flex; align-items:center; gap:8px; color:#374151; font-size:14px; cursor:pointer;">';
                html += '<input type="checkbox" id="relationReportFullPeriod" onchange="toggleRelationReportPeriod()">';
                html += '<span>Usar todo o período</span>';
                html += '</label>';
                html += '<span style="font-size:12px; color:#6b7280;">Ao marcar, o relatório ignora o filtro de datas.</span>';
                html += '</div>';
                html += '<div style="margin-top:18px; display:flex; gap:12px; flex-wrap:wrap;">';
                html += '<button class="btn btn-primary" id="relationReportOpenBtn" onclick="openRelationReportView()"><i class="fas fa-chart-line"></i> Abrir Report Executivo</button>';
                html += '<button class="btn btn-secondary" onclick="previewRelationReport()"><i class="fas fa-eye"></i> Pré-visualizar resumo</button>';
                html += '</div>';
                html += '<div id="relationReportPreview" style="display:none; margin-top:18px;"></div>';
                html += '</div>';

                document.getElementById('reportsRelationshipContent').innerHTML = html;
                toggleRelationReportPeriod();
            } catch (error) {
                showError('Erro ao carregar reports');
            }
        }

        const CLIENT_EXPORT_FIELDS = [
            { key: 'id', label: 'ID', checked: true },
            { key: 'name', label: 'Nome', checked: true },
            { key: 'company', label: 'Empresa', checked: true },
            { key: 'position', label: 'Cargo', checked: true },
            { key: 'area_of_activity', label: 'Área de Atuação', checked: false },
            { key: 'email', label: 'Email', checked: true },
            { key: 'phone', label: 'Telefone', checked: true },
            { key: 'linkedin', label: 'LinkedIn', checked: true },
            { key: 'photo_url', label: 'Foto (URL)', checked: false },
            { key: 'is_target', label: 'Contato-Alvo', checked: false },
            { key: 'is_cold_contact', label: 'Contato Frio', checked: false },
            { key: 'created_at', label: 'Data de Cadastro', checked: true },
            { key: 'updated_at', label: 'Última Atualização', checked: false }
        ];

        function renderClientExportFields() {
            const container = document.getElementById('clientExportFields');
            if (!container) return;
            container.innerHTML = CLIENT_EXPORT_FIELDS.map(field => `
                <label style="display:flex; align-items:center; gap:8px; padding:8px 10px; border:1px solid #e5e7eb; border-radius:8px; cursor:pointer; background:white;">
                    <input type="checkbox" class="client-export-field" value="${field.key}" ${field.checked ? 'checked' : ''} onchange="toggleClientExportButton()">
                    <span style="font-size:14px; color:#1f2937;">${escapeHtml(field.label)}</span>
                </label>
            `).join('');
            toggleClientExportButton();
        }

        function openClientExportModal() {
            renderClientExportFields();
            document.getElementById('clientExportModal')?.classList.add('active');
        }

        function closeClientExportModal() {
            document.getElementById('clientExportModal')?.classList.remove('active');
        }

        function clientExportSelectAll(value) {
            document.querySelectorAll('.client-export-field').forEach(input => {
                input.checked = !!value;
            });
            toggleClientExportButton();
        }

        function getSelectedClientExportFields() {
            return Array.from(document.querySelectorAll('.client-export-field:checked')).map(input => input.value);
        }

        function toggleClientExportButton() {
            const btn = document.getElementById('clientExportConfirmBtn');
            if (!btn) return;
            const hasSelection = getSelectedClientExportFields().length > 0;
            btn.disabled = !hasSelection;
            btn.style.opacity = hasSelection ? '1' : '0.6';
            btn.style.cursor = hasSelection ? 'pointer' : 'not-allowed';
        }

        function toggleRelationReportPeriod() {
            const full = document.getElementById('relationReportFullPeriod')?.checked;
            const start = document.getElementById('relationReportStart');
            const end = document.getElementById('relationReportEnd');
            if (!start || !end) return;
            start.disabled = !!full;
            end.disabled = !!full;
            start.style.opacity = full ? '0.55' : '1';
            end.style.opacity = full ? '0.55' : '1';
        }

        function getRelationReportParams() {
            const accountId = document.getElementById('relationReportAccount')?.value;
            const fullPeriod = document.getElementById('relationReportFullPeriod')?.checked;
            const startDate = document.getElementById('relationReportStart')?.value;
            const endDate = document.getElementById('relationReportEnd')?.value;
            if (!accountId) {
                throw new Error('Selecione uma conta para gerar o Relationship Report.');
            }
            if (!fullPeriod && (!startDate || !endDate)) {
                throw new Error('Selecione data inicial e final ou marque todo o período.');
            }
            return { accountId, fullPeriod, startDate, endDate };
        }

        function openRelationReportView() {
            const btn = document.getElementById('relationReportOpenBtn');
            const originalHtml = btn ? btn.innerHTML : '';
            try {
                const { accountId, fullPeriod, startDate, endDate } = getRelationReportParams();
                const params = new URLSearchParams({ account_id: accountId, full_period: fullPeriod ? 'true' : 'false' });
                if (!fullPeriod) {
                    params.set('start_date', startDate);
                    params.set('end_date', endDate);
                }
                if (btn) {
                    btn.disabled = true;
                    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Abrindo report...';
                }
                const targetUrl = `/report/relation/view?${params.toString()}`;
                window.open(targetUrl, '_blank', 'noopener');
                showToast('Abrindo Relationship Report executivo...', 'success');
            } catch (error) {
                console.error(error);
                showToast(error.message || 'Erro ao abrir Relationship Report', 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = originalHtml || '<i class="fas fa-chart-line"></i> Abrir Report Executivo';
                }
            }
        }

        async function previewRelationReport() {
            const container = document.getElementById('relationReportPreview');
            try {
                const { accountId, fullPeriod, startDate, endDate } = getRelationReportParams();
                container.style.display = 'block';
                container.innerHTML = '<div style="padding:16px; border-radius:12px; background:#f9fafb; color:#6b7280; border:1px solid #e5e7eb;">Gerando prévia...</div>';
                const params = new URLSearchParams({ account_id: accountId, full_period: fullPeriod ? 'true' : 'false' });
                if (!fullPeriod) {
                    params.set('start_date', startDate);
                    params.set('end_date', endDate);
                }
                const response = await fetch(`${API_BASE}/report/relation/preview?${params.toString()}`);
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || 'Erro ao gerar prévia');
                const counts = data.summary_counts || {};
                const highlights = (data.highlights || data.narrative?.highlights || []).map(item => `<li>${escapeHtml(item)}</li>`).join('');
                const marketContext = (data.narrative?.market_context || '').trim();
                let previewHtml = '';
                previewHtml += '<div style="padding:18px; border-radius:14px; background:linear-gradient(180deg,#f0fdf4,#ffffff); border:1px solid #bbf7d0;">';
                previewHtml += `<div style="display:flex; justify-content:space-between; gap:12px; align-items:flex-start; flex-wrap:wrap; margin-bottom:14px;"><div><h4 style="margin:0; color:#065f46;">Prévia do resumo</h4><p style="margin:6px 0 0 0; color:#6b7280; font-size:13px;">${escapeHtml(data.account?.name || '')}</p></div><div style="font-size:12px; color:#047857; background:#dcfce7; border:1px solid #a7f3d0; border-radius:999px; padding:6px 10px;">${data.period?.full_period ? 'Período completo' : `${escapeHtml(data.period?.start_date || '')} a ${escapeHtml(data.period?.end_date || '')}`}</div></div>`;
                previewHtml += '<div style="display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:10px; margin-bottom:14px;">';
                previewHtml += `<div style="padding:12px; background:white; border:1px solid #d1fae5; border-radius:12px;"><div style="font-size:11px; color:#6b7280;">Contatos</div><div style="font-size:20px; font-weight:700; color:#065f46;">${counts.contacts || 0}</div></div>`;
                previewHtml += `<div style="padding:12px; background:white; border:1px solid #d1fae5; border-radius:12px;"><div style="font-size:11px; color:#6b7280;">Atividades</div><div style="font-size:20px; font-weight:700; color:#065f46;">${(counts.activities || 0) + (counts.account_activities || 0)}</div></div>`;
                previewHtml += `<div style="padding:12px; background:white; border:1px solid #d1fae5; border-radius:12px;"><div style="font-size:11px; color:#6b7280;">Kanban</div><div style="font-size:20px; font-weight:700; color:#065f46;">${counts.kanban_cards || 0}</div></div>`;
                previewHtml += `<div style="padding:12px; background:white; border:1px solid #d1fae5; border-radius:12px;"><div style="font-size:11px; color:#6b7280;">Mapeamentos</div><div style="font-size:20px; font-weight:700; color:#065f46;">${counts.mapping_items || 0}</div></div>`;
                previewHtml += '</div>';
                previewHtml += `<div style="background:white; border:1px solid #e5e7eb; border-radius:12px; padding:14px; margin-bottom:12px;"><div style="font-size:12px; text-transform:uppercase; letter-spacing:0.08em; color:#047857; margin-bottom:8px;">Resumo executivo</div><div style="color:#374151; line-height:1.6; white-space:pre-line;">${escapeHtml(data.narrative?.executive_summary || 'Sem resumo disponível.')}</div>${marketContext ? `<div class="rr-market-context"><h3 style="font-size:13px; color:#6b7280; text-transform:uppercase; letter-spacing:.05em; margin:18px 0 6px;">Contexto de Mercado</h3><p style="font-size:14px; line-height:1.7; color:#374151; margin:0;">${escapeHtml(marketContext)}</p></div>` : ''}</div>`;
                previewHtml += '<div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">';
                previewHtml += `<div style="background:white; border:1px solid #e5e7eb; border-radius:12px; padding:14px;"><div style="font-size:12px; text-transform:uppercase; letter-spacing:0.08em; color:#047857; margin-bottom:8px;">Destaques</div><ul style="margin:0; padding-left:18px; color:#374151; line-height:1.6;">${highlights || '<li>Sem destaques.</li>'}</ul></div>`;
                previewHtml += '<div style="background:white; border:1px solid #e5e7eb; border-radius:12px; padding:14px;">';
                previewHtml += '<div style="font-size:12px; text-transform:uppercase; letter-spacing:0.08em; color:#047857; margin-bottom:8px;">Tópicos</div>';
                previewHtml += Object.entries(data.topics || {}).map(([key, value]) => `<div style="display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid #f3f4f6;"><span style="color:#374151;">${escapeHtml(key)}</span><strong style="color:#065f46;">${value}</strong></div>`).join('');
                previewHtml += '</div>';
                previewHtml += '</div></div>';
                container.innerHTML = previewHtml;
            } catch (error) {
                container.style.display = 'block';
                container.innerHTML = `<div style="padding:16px; border-radius:12px; background:#fef2f2; color:#b91c1c; border:1px solid #fecaca;">${escapeHtml(error.message || 'Erro ao gerar prévia')}</div>`;
            }
        }


        function resetClientPhotoField() {
            const photoInput = document.getElementById('photoInput');
            const photoPreview = document.getElementById('photoPreview');
            const removePhotoFlag = document.getElementById('removePhotoFlag');
            const removePhotoBtn = document.getElementById('removePhotoBtn');
            const removePhotoHelp = document.getElementById('removePhotoHelp');

            if (photoInput) {
                photoInput.value = '';
            }
            const autofindPhotoUrl = document.getElementById('autofindPhotoUrl');
            if (autofindPhotoUrl) autofindPhotoUrl.value = '';
            clearClientAutoPicCandidates();

            if (photoPreview) {
                photoPreview.removeAttribute('src');
                photoPreview.style.display = 'none';
            }

            if (removePhotoFlag) removePhotoFlag.value = '0';
            if (removePhotoBtn) {
                removePhotoBtn.style.display = 'none';
                removePhotoBtn.innerHTML = '<i class="fas fa-trash"></i> Excluir foto atual';
                removePhotoBtn.classList.remove('btn-secondary');
                removePhotoBtn.classList.add('btn-danger');
            }
            if (removePhotoHelp) removePhotoHelp.style.display = 'none';
        }

        function toggleRemovePhoto() {
            const removePhotoFlag = document.getElementById('removePhotoFlag');
            const removePhotoBtn = document.getElementById('removePhotoBtn');
            const removePhotoHelp = document.getElementById('removePhotoHelp');
            const photoPreview = document.getElementById('photoPreview');

            if (!removePhotoFlag || !removePhotoBtn) return;

            const willRemove = removePhotoFlag.value !== '1';
            removePhotoFlag.value = willRemove ? '1' : '0';

            if (willRemove) {
                if (photoPreview) {
                    photoPreview.removeAttribute('src');
                    photoPreview.style.display = 'none';
                }
                removePhotoBtn.innerHTML = '<i class="fas fa-undo"></i> Desfazer exclusão da foto';
                removePhotoBtn.classList.remove('btn-danger');
                removePhotoBtn.classList.add('btn-secondary');
                if (removePhotoHelp) removePhotoHelp.style.display = 'block';
            } else {
                removePhotoBtn.innerHTML = '<i class="fas fa-trash"></i> Excluir foto atual';
                removePhotoBtn.classList.remove('btn-secondary');
                removePhotoBtn.classList.add('btn-danger');
                if (removePhotoHelp) removePhotoHelp.style.display = 'none';
                const currentPhotoUrl = removePhotoBtn.dataset.currentPhotoUrl || '';
                if (currentPhotoUrl && photoPreview) {
                    photoPreview.src = currentPhotoUrl;
                    photoPreview.style.display = 'block';
                }
            }
        }

        // Open Client Modal
        function openClientModal() {
            currentEditingClientId = null;
            document.getElementById('clientModalTitle').textContent = 'Novo Cliente';
            document.getElementById('clientForm').reset();
            resetClientPhotoField();
            document.getElementById('clientModal').classList.add('active');
        }

        // Close Client Modal
        function closeClientModal(fromSave = false) {
            resetClientPhotoField();
            // Se fechado manualmente (cancelar/X), limpa o contexto do org map
            if (!fromSave) _orgMapOpenContext = null;
            document.getElementById('clientModal').classList.remove('active');
        }

        // Open Activity Modal
        async function openActivityModal() {
            currentEditingActivityId = null;
            document.getElementById('activityModalTitle').textContent = 'Nova Atividade';
            document.getElementById('activityForm').reset();
            await loadClientSelect();
            document.getElementById('activityModal').classList.add('active');
        }

        // Close Activity Modal
        function closeActivityModal() {
            // Reabilitar o select de cliente caso tenha sido bloqueado
            const clientSelect = document.getElementById('clientSelect');
            if (clientSelect) {
                clientSelect.disabled = false;
            }

            // Reabilitar o select de empresa caso tenha sido bloqueado
            const companySelect = document.getElementById('companySelect');
            if (companySelect) {
                companySelect.disabled = false;
            }

            const activityModalEl = document.getElementById('activityModal');
            activityModalEl.classList.remove('active');
            // Restaura o z-index padrão caso tenha sido elevado por sobrepor a ficha.
            activityModalEl.style.zIndex = '';
        }

        // Open Quick Activity Modal (from Dashboard)
        async function openQuickActivityModal(clientId, clientName, clientCompany) {
            currentEditingActivityId = null;
            document.getElementById('activityModalTitle').textContent = `Nova Atividade - ${clientName}`;
            document.getElementById('activityForm').reset();

            // Carregar clientes e pré-selecionar empresa
            await loadClientSelect(clientCompany);

            // Pré-selecionar o cliente
            const clientSelect = document.getElementById('clientSelect');
            if (clientSelect) {
                clientSelect.value = clientId;
                clientSelect.disabled = true; // Bloquear alteração do cliente
            }

            // Bloquear também a empresa
            const companySelect = document.getElementById('companySelect');
            if (companySelect) {
                companySelect.disabled = true;
            }

            const activityModalEl = document.getElementById('activityModal');
            // Se aberto por cima da ficha do contato, elevar para ficar acima do profileModal.
            if (_profileModalOpenClientId) {
                activityModalEl.style.zIndex = '1100';
            }
            activityModalEl.classList.add('active');
        }

        // Open Import Modal
        function openImportModal() {
            document.getElementById('importModal').classList.add('active');
        }

        // Close Import Modal
        function closeImportModal() {
            document.getElementById('importModal').classList.remove('active');
        }

        // Download Excel Template
        function downloadTemplate() {
            const link = document.createElement('a');
            link.setAttribute('href', `${API_BASE}/importar-clientes/template-xlsx`);
            link.setAttribute('download', 'template_clientes.xlsx');
            link.style.visibility = 'hidden';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        }

        // Handle Excel Upload
        async function handleExcelUpload(event) {
            const file = event.target.files[0];
            if (!file) return;
            
            const statusDiv = document.getElementById('importStatus');
            statusDiv.style.display = 'block';
            statusDiv.className = 'alert alert-info';
            statusDiv.textContent = 'Processando arquivo...';
            
            try {
                const formData = new FormData();
                formData.append('file', file);
                
                const response = await fetch(`${API_BASE}/importar-clientes`, {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    statusDiv.className = 'alert alert-success';
                    statusDiv.textContent = `Sucesso! ${result.imported} clientes importados.`;
                    setTimeout(() => {
                        closeImportModal();
                        loadClients();
                        loadDashboard();
                    }, 2000);
                } else {
                    statusDiv.className = 'alert alert-error';
                    statusDiv.textContent = result.error || 'Erro ao importar arquivo';
                }
            } catch (error) {
                statusDiv.className = 'alert alert-error';
                statusDiv.textContent = 'Erro ao processar arquivo: ' + error.message;
            }
        }

        // Load Client Select
        async function loadClientSelect(selectedCompany = '') {
            try {
                const response = await fetch(`${API_BASE}/clientes`);
                const data = await response.json();

                clients = data;
                const companies = [...new Set(data.map(c => c.company).filter(Boolean))].sort((a,b) => a.localeCompare(b, 'pt-BR'));

                let companyHtml = '<option value="">Selecione uma empresa...</option>';
                companies.forEach(company => {
                    companyHtml += `<option value="${escapeHtml(company)}">${escapeHtml(company)}</option>`;
                });

                document.getElementById('companySelect').innerHTML = companyHtml;
                selectedCompanyForActivity = selectedCompany || '';
                if (selectedCompany) document.getElementById('companySelect').value = selectedCompany;
                filterClientsByCompany();
            } catch (error) {
                showError('Erro ao carregar clientes');
            }
        }

        function filterClientsByCompany() {
            const company = document.getElementById('companySelect').value;
            selectedCompanyForActivity = company;
            const filtered = clients.filter(client => !company || client.company === company);

            let html = '<option value="">Selecione um cliente...</option>';
            filtered.forEach(client => {
                html += `<option value="${client.id}">${client.name}</option>`;
            });
            document.getElementById('clientSelect').innerHTML = html;
        }

        // Preview Photo
        function previewPhoto(event) {
            const file = event.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = (e) => {
                    document.getElementById('photoPreview').src = e.target.result;
                    document.getElementById('photoPreview').style.display = 'block';
                const autofindPhotoUrl = document.getElementById('autofindPhotoUrl');
                if (autofindPhotoUrl) autofindPhotoUrl.value = '';
                clearClientAutoPicCandidates();
                    const removePhotoFlag = document.getElementById('removePhotoFlag');
                    const removePhotoHelp = document.getElementById('removePhotoHelp');
                    if (removePhotoFlag) removePhotoFlag.value = '0';
                    if (removePhotoHelp) removePhotoHelp.style.display = 'none';
                };
                reader.readAsDataURL(file);
            }
        }

        function previewProfilePhoto(event) {
            const file = event.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (e) => {
                const preview = document.getElementById('profilePhotoPreview');
                preview.src = e.target.result;
                preview.style.display = 'block';
            };
            reader.readAsDataURL(file);
        }



        function setPastedImageToInput(blob) {
            const photoInput = document.getElementById('photoInput');
            if (!photoInput || !blob) return;

            const file = new File([blob], `foto_colada_${Date.now()}.png`, { type: blob.type || 'image/png' });
            const dt = new DataTransfer();
            dt.items.add(file);
            photoInput.files = dt.files;

            const reader = new FileReader();
            reader.onload = (e) => {
                document.getElementById('photoPreview').src = e.target.result;
                document.getElementById('photoPreview').style.display = 'block';
                const autofindPhotoUrl = document.getElementById('autofindPhotoUrl');
                if (autofindPhotoUrl) autofindPhotoUrl.value = '';
                clearClientAutoPicCandidates();
            };
            reader.readAsDataURL(file);
        }

        document.addEventListener('paste', (event) => {
            const clientModal = document.getElementById('clientModal');
            const accountModal = document.getElementById('accountModal');
            const clientOpen = !!(clientModal && clientModal.classList.contains('active'));
            const accountOpen = !!accountModal;
            if (!clientOpen && !accountOpen) return;

            const items = event.clipboardData && event.clipboardData.items ? event.clipboardData.items : [];
            for (const item of items) {
                if (item.type && item.type.startsWith('image/')) {
                    const blob = item.getAsFile();
                    if (blob) {
                        const autoPicOpen = document.getElementById('clientAutoPicCandidates')?.classList.contains('open');
                        if (accountOpen) setPastedImageToAccountLogo(blob);
                        else if (autoPicOpen) {
                            applyAutoPicImageFromBlob(blob);
                        } else {
                            setPastedImageToInput(blob);
                        }
                        showSuccess('Imagem colada com sucesso!');
                        event.preventDefault();
                        break;
                    }
                }
            }
        });
        function renderAutoPicSlots() {
            const el = document.getElementById('clientAutoPicCandidates');
            if (!el) return;
            el.classList.add('open');
            const isLoading = autoPicSlots._loading === true;
            const hasImages = autoPicSlots.some(Boolean);

            if (isLoading) {
                el.innerHTML = `
                    <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:8px;">
                        <strong style="color:#065f46; font-size:12px;">&#10024; AutoPic — Buscando imagens...</strong>
                        <button type="button" class="btn btn-secondary btn-small" onclick="clearClientAutoPicCandidates()">Cancelar</button>
                    </div>
                    <div style="display:flex; align-items:center; gap:10px; padding:16px 0; color:#047857;">
                        <span style="font-size:22px;">&#9203;</span>
                        <span>Buscando as 3 primeiras imagens automaticamente...</span>
                    </div>
                `;
                return;
            }

            el.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:8px;">
                    <strong style="color:#065f46; font-size:12px;">&#10024; AutoPic — Clique na imagem desejada</strong>
                    <button type="button" class="btn btn-secondary btn-small" onclick="clearClientAutoPicCandidates()">Descartar</button>
                </div>
                <div class="autopic-candidates-grid" style="align-items:flex-start;">
                    ${[0,1,2].map((idx) => {
                        const data = autoPicSlots[idx];
                        const content = data
                            ? `<img src="${data}" alt="AutoPic ${idx+1}" style="cursor:pointer;" onclick="chooseAutoPicSlot(${idx})">`
                            : `<div style="display:flex;align-items:center;justify-content:center;height:80px;color:#9ca3af;font-size:12px;">Sem imagem</div>`;
                        return `<div class="autopic-slot"><div class="autopic-slot-title">Imagem ${idx+1}</div><div class="autopic-slot-box" onclick="${data ? 'chooseAutoPicSlot(' + idx + ')' : ''}">${content}</div></div>`;
                    }).join('')}
                </div>
                <small style="display:block; margin-top:8px; color:#047857;">Clique na imagem que deseja usar como foto do contato.</small>
            `;
        }

        function applyAutoPicImageFromBlob(blob, slotIndex = null) {
            // Mantido para compatibilidade com o listener de paste (caso o usuário cole manualmente)
            if (!blob) return;
            let targetSlot = Number.isInteger(slotIndex) ? slotIndex : autoPicActiveSlot;
            if (targetSlot < 0 || targetSlot > 2) targetSlot = 0;
            const reader = new FileReader();
            reader.onload = (e) => {
                autoPicSlots[targetSlot] = e.target.result;
                if (targetSlot < 2) autoPicActiveSlot = targetSlot + 1;
                renderAutoPicSlots();
            };
            reader.readAsDataURL(blob);
        }

        function clearClientAutoPicCandidates() {
            const el = document.getElementById('clientAutoPicCandidates');
            if (!el) return;
            el.classList.remove('open');
            el.innerHTML = '';
            autoPicSlots = [null, null, null];
            autoPicActiveSlot = 0;
            autoPicGoogleTab = null;
        }

        async function chooseAutoPicSlot(index) {
            const image = autoPicSlots[index];
            if (!image) return;

            const name = (document.querySelector('#clientForm [name="name"]')?.value || '').trim();

            // Mostrar estado de carregamento no slot selecionado
            document.querySelectorAll('.autopic-slot-box').forEach((box, idx) => {
                box.classList.toggle('active', idx === index);
            });

            try {
                let photoUrl = '';

                if (image.startsWith('data:image/')) {
                    // Imagem em base64 — salvar no servidor via endpoint dedicado
                    const response = await fetch(`${API_BASE}/clients/autofind-photo-base64`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ data_url: image, name })
                    });
                    const payload = await response.json().catch(() => ({}));
                    if (!response.ok) throw new Error(payload.error || 'Não foi possível salvar a imagem.');
                    photoUrl = payload.photo_url || '';
                } else {
                    // URL externa — baixar e salvar no servidor
                    // Tentar a URL selecionada; se falhar (ex: 403), tentar candidatos de fallback
                    const allCandidates = autoPicSlots._allCandidates || [];
                    const usedUrls = new Set(autoPicSlots.filter(Boolean));
                    const fallbackUrls = allCandidates.filter(u => !usedUrls.has(u) && u !== image);
                    
                    let lastError = null;
                    let urlsToTry = [image, ...fallbackUrls];
                    
                    for (const urlToTry of urlsToTry) {
                        try {
                            const response = await fetch(`${API_BASE}/clients/autofind-photo`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ image_url: urlToTry, name })
                            });
                            const payload = await response.json().catch(() => ({}));
                            if (!response.ok) {
                                lastError = payload.error || 'Não foi possível importar a imagem.';
                                continue; // tentar próxima URL
                            }
                            photoUrl = payload.photo_url || '';
                            lastError = null;
                            break; // sucesso!
                        } catch (e) {
                            lastError = e.message;
                        }
                    }
                    
                    if (lastError || !photoUrl) {
                        throw new Error(lastError || 'Não foi possível importar nenhuma das imagens encontradas.');
                    }
                }

                const autofindPhotoUrl = document.getElementById('autofindPhotoUrl');
                if (autofindPhotoUrl) autofindPhotoUrl.value = photoUrl;

                const photoInput = document.getElementById('photoInput');
                if (photoInput) photoInput.value = '';

                const preview = document.getElementById('photoPreview');
                if (preview) {
                    preview.src = photoUrl || image;
                    preview.style.display = 'block';
                }

                const removePhotoFlag = document.getElementById('removePhotoFlag');
                if (removePhotoFlag) removePhotoFlag.value = '0';

                clearClientAutoPicCandidates();
                showSuccess('Foto definida via AutoPic! Salve o contato para confirmar.');
            } catch (error) {
                showError(error.message || 'Falha ao usar imagem do AutoPic.');
            }
        }

        // ---- LinkedIn AutoFill — modal para o cadastro de contato ----

        // Estado do modal
        let _clImportedProfileText = '';
        let _clImportedPhotoUrl = '';
        let _clImportedProfileUrl = '';

        function _clEnsureBunnyStyle() {
            if (document.getElementById('cl-bunny-style')) return;
            const s = document.createElement('style');
            s.id = 'cl-bunny-style';
            s.textContent = `
                @keyframes cl-bunny-hop { 0%,100%{transform:translateY(-50%) scaleY(1)} 50%{transform:translateY(-70%) scaleY(.85)} }
                #clModalBunny { animation: cl-bunny-hop .5s ease-in-out infinite; }
            `;
            document.head.appendChild(s);
        }

        function _clModalSetProgress(pct, step) {
            const bar = document.getElementById('clModalProgressBar');
            const stepEl = document.getElementById('clModalProgressStep');
            const pctEl = document.getElementById('clModalProgressPct');
            const p = Math.min(100, Math.max(0, pct));
            if (bar) bar.style.width = p + '%';
            if (stepEl) stepEl.textContent = step || '';
            if (pctEl) pctEl.textContent = Math.round(p) + '%';
        }

        async function openClientLinkedinModal() {
            _clImportedProfileText = '';
            _clImportedPhotoUrl = '';
            _clImportedProfileUrl = '';

            // Pré-preenche URL do campo do form principal
            const linkedinInput = document.getElementById('clientLinkedinInput');
            _clImportedProfileUrl = (linkedinInput?.value || '').trim();

            // Reseta modal
            const formArea = document.getElementById('clModalFormArea');
            const progressArea = document.getElementById('clModalProgressArea');
            if (formArea) formArea.style.display = '';
            if (progressArea) progressArea.style.display = 'none';

            const textarea = document.getElementById('clModalProfileText');
            if (textarea) textarea.value = '';

            const importFeedback = document.getElementById('clModalImportFeedback');
            if (importFeedback) importFeedback.textContent = '';

            // Mostra modal
            document.getElementById('clientLinkedinModal').classList.add('active');
            _clEnsureBunnyStyle();

            // Checa extensão
            await clModalCheckExtension();
        }

        function closeClientLinkedinModal() {
            document.getElementById('clientLinkedinModal').classList.remove('active');
        }

        async function clModalCheckExtension() {
            const statusIcon = document.getElementById('clModalExtStatusIcon');
            const statusText = document.getElementById('clModalExtStatusText');
            const checkBtn = document.getElementById('clModalCheckBtn');
            const importArea = document.getElementById('clModalExtImportArea');
            const installArea = document.getElementById('clModalInstallArea');
            const extStatus = document.getElementById('clModalExtStatus');

            if (statusIcon) statusIcon.textContent = '⏳';
            if (statusText) { statusText.textContent = 'Verificando extensão...'; statusText.style.color = '#6b7280'; }
            if (importArea) importArea.style.display = 'none';
            if (installArea) installArea.style.display = 'none';

            const installed = await _checkAutoTocaExtensionInstalled();

            if (installed) {
                if (statusIcon) statusIcon.textContent = '✅';
                if (statusText) { statusText.textContent = 'Extensão instalada e ativa!'; statusText.style.color = '#059669'; }
                if (extStatus) extStatus.style.background = '#f0fdf4';
                if (extStatus) extStatus.style.borderColor = '#bbf7d0';
                if (importArea) importArea.style.display = '';
                if (installArea) installArea.style.display = 'none';
            } else {
                if (statusIcon) statusIcon.textContent = '❌';
                if (statusText) { statusText.textContent = 'Extensão não encontrada.'; statusText.style.color = '#b91c1c'; }
                if (extStatus) extStatus.style.background = '#fff8f8';
                if (extStatus) extStatus.style.borderColor = '#fecaca';
                if (importArea) importArea.style.display = 'none';
                if (installArea) installArea.style.display = '';
            }
            if (checkBtn) checkBtn.style.display = '';
        }

        async function clModalImportFromExtension() {
            const btn = document.getElementById('clModalImportBtn');
            const feedback = document.getElementById('clModalImportFeedback');
            const originalHtml = btn?.innerHTML;

            if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-circle-notch fa-spin" style="margin-right:5px;"></i> Buscando perfil...'; }
            if (feedback) feedback.textContent = '';

            try {
                const result = await _sendAutoTocaCommand({ command: 'get_linkedin_profile' });

                if (!result?.ok) {
                    if (feedback) {
                        feedback.style.color = '#b45309';
                        feedback.innerHTML = `<i class="fas fa-info-circle"></i> Nenhum perfil capturado ainda. Abra um perfil no LinkedIn e clique no botão <strong>✦ Analisar com AutoToca</strong> que aparece na página. <button onclick="abrirGuiaLinkedIn()" class="btn btn-secondary btn-small" style="margin-left:6px;">Ver tutorial</button>`;
                    }
                    return;
                }

                // Salva os dados importados
                _clImportedProfileText = result.profileText || '';
                _clImportedPhotoUrl = result.profilePhotoUrl || '';
                _clImportedProfileUrl = result.profileUrl || _clImportedProfileUrl;

                // Popula textarea e ajusta cor para texto legível
                const textarea = document.getElementById('clModalProfileText');
                if (textarea) {
                    textarea.value = _clImportedProfileText;
                    textarea.style.color = _clImportedProfileText ? '#374151' : '#9ca3af';
                }

                const photoInfo = _clImportedPhotoUrl ? ' · foto capturada' : '';
                if (feedback) {
                    feedback.style.color = '#059669';
                    feedback.innerHTML = `<i class="fas fa-check-circle"></i> Perfil importado com sucesso${photoInfo}! Clique em <strong>Processar e Preencher</strong>.`;
                }

            } catch (e) {
                if (feedback) {
                    feedback.style.color = '#b91c1c';
                    feedback.innerHTML = `<i class="fas fa-exclamation-triangle"></i> Erro ao comunicar com a extensão: ${e.message}. Verifique se a extensão está ativa.`;
                }
            } finally {
                if (btn) { btn.disabled = false; btn.innerHTML = originalHtml; }
            }
        }

        async function clModalProcess() {
            const profileText = (document.getElementById('clModalProfileText')?.value || '').trim();
            const photoUrl = _clImportedPhotoUrl || '';
            const linkedinUrl = _clImportedProfileUrl || (document.getElementById('clientLinkedinInput')?.value || '').trim();

            if (!profileText) {
                showError('Cole o texto do perfil LinkedIn ou use a extensão para importar antes de processar.');
                return;
            }

            const formArea = document.getElementById('clModalFormArea');
            const progressArea = document.getElementById('clModalProgressArea');
            if (formArea) formArea.style.display = 'none';
            if (progressArea) progressArea.style.display = '';
            _clModalSetProgress(5, 'Iniciando...');

            try {
                const res = await fetch(`${API_BASE}/clientes/linkedin-autofill`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        linkedin_url: linkedinUrl,
                        profile_text: profileText,
                        extension_photo_url: photoUrl
                    })
                });
                const payload = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(payload.error || 'Falha ao iniciar AutoFill.');

                const taskId = payload.task_id;
                if (!taskId) throw new Error('Resposta inesperada do servidor.');

                const poll = setInterval(async () => {
                    try {
                        const tr = await fetch(`${API_BASE}/tasks/${taskId}`);
                        const task = await tr.json();
                        _clModalSetProgress(task.progress || 5, task.step || '...');

                        if (task.status === 'done') {
                            clearInterval(poll);
                            closeClientLinkedinModal();
                            _clApplyLinkedInResult(task.result || {});
                            // Preenche URL do LinkedIn no campo do form principal
                            if (linkedinUrl) {
                                const liInput = document.getElementById('clientLinkedinInput');
                                if (liInput && !liInput.value) liInput.value = linkedinUrl;
                            }
                            showSuccess('Campos preenchidos via LinkedIn! Confira os dados antes de salvar.');
                        } else if (task.status === 'error') {
                            clearInterval(poll);
                            if (formArea) formArea.style.display = '';
                            if (progressArea) progressArea.style.display = 'none';
                            showError(task.error || 'Erro ao processar o perfil LinkedIn.');
                        }
                    } catch (e) {
                        clearInterval(poll);
                        if (formArea) formArea.style.display = '';
                        if (progressArea) progressArea.style.display = 'none';
                        showError('Erro ao verificar status do AutoFill.');
                    }
                }, 800);
            } catch (e) {
                if (formArea) formArea.style.display = '';
                if (progressArea) progressArea.style.display = 'none';
                showError(e.message || 'Erro ao iniciar AutoFill LinkedIn.');
            }
        }

        function _clApplyLinkedInResult(result) {
            const form = document.getElementById('clientForm');
            if (!form) return;

            // Nome
            if (result.nome) form.name.value = result.nome;

            // Empresa — tenta selecionar no dropdown; se não existe, vai para "outro"
            if (result.empresa) {
                const companySel = document.getElementById('clientCompanySelect');
                if (companySel) {
                    const opt = Array.from(companySel.options).find(o =>
                        o.value && o.value !== '__other__' && o.value.toLowerCase() === result.empresa.toLowerCase()
                    );
                    if (opt) {
                        companySel.value = opt.value;
                        toggleOtherField('company');
                    } else {
                        companySel.value = '__other__';
                        toggleOtherField('company');
                        const other = document.getElementById('clientCompanyOther');
                        if (other) other.value = result.empresa;
                    }
                }
            }

            // Cargo — mesma lógica
            if (result.cargo) {
                const positionSel = document.getElementById('clientPositionSelect');
                if (positionSel) {
                    const opt = Array.from(positionSel.options).find(o =>
                        o.value && o.value !== '__other__' && o.value.toLowerCase() === result.cargo.toLowerCase()
                    );
                    if (opt) {
                        positionSel.value = opt.value;
                        toggleOtherField('position');
                    } else {
                        positionSel.value = '__other__';
                        toggleOtherField('position');
                        const other = document.getElementById('clientPositionOther');
                        if (other) other.value = result.cargo;
                    }
                }
            }

            // Área de Atuação
            if (result.area_atuacao && form.area_of_activity) {
                form.area_of_activity.value = result.area_atuacao;
            }

            // Email (só preenche se campo vazio)
            if (result.email && form.email && !form.email.value) {
                form.email.value = result.email;
            }

            // Foto via autofind_photo_url
            if (result.photo_url) {
                const autofindInput = document.getElementById('autofindPhotoUrl');
                if (autofindInput) autofindInput.value = result.photo_url;
                const preview = document.getElementById('photoPreview');
                if (preview) {
                    preview.src = result.photo_url;
                    preview.style.display = 'block';
                }
                const removeBtn = document.getElementById('removePhotoBtn');
                if (removeBtn) removeBtn.style.display = 'inline-flex';
            }
        }

        async function openClientAutoPicSearch() {
            const name = (document.querySelector('#clientForm [name="name"]')?.value || '').trim();
            const company = (getClientFieldValue('company') || '').trim();

            if (!name || !company) {
                await openSystemDialog({
                    title: 'AutoPic',
                    message: 'Preencha Nome e Empresa antes de usar o AutoPic.'
                });
                return;
            }

            // Inicializar slots e mostrar estado de carregamento
            autoPicSlots = [null, null, null];
            autoPicSlots._loading = true;
            autoPicActiveSlot = 0;
            renderAutoPicSlots();

            try {
                const params = new URLSearchParams({ name, company });
                const response = await fetch(`${API_BASE}/clients/autofind-photo-candidates?${params}`);
                const payload = await response.json().catch(() => ({}));

                if (!response.ok) throw new Error(payload.error || 'Não foi possível buscar imagens.');

                const candidates = payload.candidates || [];
                if (candidates.length === 0) {
                    clearClientAutoPicCandidates();
                    await openSystemDialog({
                        title: 'AutoPic',
                        message: 'Nenhuma imagem encontrada para este contato. Tente adicionar uma foto manualmente.'
                    });
                    return;
                }

                // Preencher slots com as URLs das imagens encontradas
                // Armazenar todos os candidatos para fallback (caso alguma imagem retorne 403)
                autoPicSlots = [null, null, null];
                autoPicSlots._loading = false;
                autoPicSlots._allCandidates = candidates; // todos os candidatos para fallback
                candidates.slice(0, 3).forEach((url, i) => {
                    autoPicSlots[i] = url;
                });
                renderAutoPicSlots();
            } catch (error) {
                clearClientAutoPicCandidates();
                showError(error.message || 'Falha ao buscar imagens via AutoPic.');
            }
        }

        // Save Client
        // Save Client
        async function saveClient(event) {
            event.preventDefault();
            const formData = new FormData(document.getElementById('clientForm'));
            
            try {
                const url = currentEditingClientId 
                    ? `${API_BASE}/clientes/${currentEditingClientId}`
                    : `${API_BASE}/clientes`;
                
                const response = await fetch(url, {
                    method: currentEditingClientId ? 'PUT' : 'POST',
                    body: formData
                });

                if (response.ok) {
                    const result = await response.json();
                    showSuccess(currentEditingClientId ? 'Cliente atualizado!' : 'Cliente cadastrado!');
                    
                    // Verificar se foi uma sugestão de cargo faltante (apenas ao criar novo cliente)
                    if (!currentEditingClientId && window.currentSuggestion && window.currentSuggestion.type === 'missing_position') {
                        const company = formData.get('company');
                        const position = formData.get('position');
                        if (company === window.currentSuggestion.data.company && position === window.currentSuggestion.data.position) {
                            await markSuggestionComplete(window.currentSuggestion.id);
                            window.currentSuggestion = null;
                        }
                    }
                    
                    // Verificar se foi uma sugestão de completar cadastro (apenas ao editar)
                    if (currentEditingClientId && window.currentSuggestion && window.currentSuggestion.type === 'incomplete_profile') {
                        const clientId = parseInt(currentEditingClientId);
                        if (clientId === window.currentSuggestion.data.client_id) {
                            // Verificar se todos os campos foram preenchidos
                            const email = formData.get('email');
                            const phone = formData.get('phone');
                            const photo = formData.get('photo');
                            
                            if (email && phone && (photo || result.photo_url)) {
                                await markSuggestionComplete(window.currentSuggestion.id);
                                window.currentSuggestion = null;
                            }
                        }
                    }
                    
                    const wasFromOrgMap = !!_orgMapOpenContext;
                    closeClientModal(true);
                    loadClients();
                    loadDashboard();
                    if (wasFromOrgMap) {
                        _orgMapOpenContext = null;
                        await loadOrganizationalMapping();
                    }
                } else {
                    showError('Erro ao salvar cliente');
                }
            } catch (error) {
                showError('Erro ao salvar cliente: ' + error.message);
            }
        }

        // Edit Client
        async function editClient(id) {
            const client = clients.find(c => c.id === id);
            if (client) {
                currentEditingClientId = id;
                document.getElementById('clientModalTitle').textContent = 'Editar Cliente';
                document.getElementById('clientForm').name.value = client.name;
                document.getElementById('clientForm').company.value = client.company;
                document.getElementById('clientForm').position.value = client.position;
                document.getElementById('clientForm').email.value = client.email || '';
                document.getElementById('clientForm').phone.value = client.phone || '';
                if (document.getElementById('clientForm').linkedin) document.getElementById('clientForm').linkedin.value = client.linkedin || '';

                resetClientPhotoField();
                if (client.photo_url) {
                    const preview = document.getElementById('photoPreview');
                    const removePhotoBtn = document.getElementById('removePhotoBtn');
                    preview.src = client.photo_url;
                    preview.style.display = 'block';
                    if (removePhotoBtn) {
                        removePhotoBtn.style.display = 'inline-flex';
                        removePhotoBtn.dataset.currentPhotoUrl = client.photo_url;
                    }
                }

                document.getElementById('clientModal').classList.add('active');
            }
        }

        // Delete Client
        async function deleteClient(id, options = {}) {
            if (await uiConfirm('Tem certeza que deseja excluir este contato? Esta ação não pode ser desfeita.', 'Excluir contato')) {
                try {
                    const response = await fetch(`${API_BASE}/clientes/${id}`, {
                        method: 'DELETE'
                    });

                    if (response.ok) {
                        if (options && options.closeProfileOnSuccess) {
                            closeProfileModal();
                        }
                        showSuccess('Contato excluído com sucesso!');
                        loadClients();
                        loadDashboard();
                    } else {
                        showError('Erro ao excluir contato');
                    }
                } catch (error) {
                    showError('Erro ao excluir contato');
                }
            }
        }

        async function archiveClient(id, options = {}) {
            const client = clients.find(c => Number(c.id) === Number(id)) || {};
            const choice = await openArchiveContactDialog(client);
            if (!choice || !choice.confirmed) return;

            try {
                const response = await fetch(`${API_BASE}/clientes/${id}/arquivar`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ remove_company: !!choice.removeCompany })
                });

                if (response.ok) {
                    if (options && options.closeProfileOnSuccess) {
                        closeProfileModal();
                    }
                    showSuccess(choice.removeCompany ? 'Contato arquivado e empresa removida com sucesso!' : 'Contato arquivado com sucesso!');
                    loadClients();
                    loadDashboard();
                } else {
                    showError('Erro ao arquivar contato');
                }
            } catch (error) {
                showError('Erro ao arquivar contato');
            }
        }

        // Save Activity
        async function saveActivity(event) {
            event.preventDefault();
            const formData = new FormData(document.getElementById('activityForm'));
            
            // Campos disabled não são enviados no FormData, então precisamos adicionar manualmente
            const clientSelect = document.getElementById('clientSelect');
            if (clientSelect && clientSelect.disabled) {
                formData.set('client_id', clientSelect.value);
            }

            try {
                const url = currentEditingActivityId 
                    ? `${API_BASE}/atividades/${currentEditingActivityId}`
                    : `${API_BASE}/atividades`;

                const response = await fetch(url, {
                    method: currentEditingActivityId ? 'PUT' : 'POST',
                    body: formData
                });

                if (response.ok) {
                    showSuccess(currentEditingActivityId ? 'Atividade atualizada!' : 'Atividade registrada!');
                    
                    // Verificar se foi uma sugestão de contato atrasado (apenas ao criar nova atividade)
                    if (!currentEditingActivityId && window.currentSuggestion && window.currentSuggestion.type === 'contact_overdue') {
                        const clientId = parseInt(formData.get('client_id'));
                        if (clientId === window.currentSuggestion.data.client_id) {
                            await markSuggestionComplete(window.currentSuggestion.id);
                            window.currentSuggestion = null;
                        }
                    }
                    
                    closeActivityModal();
                    loadActivities();
                    loadDashboard();
                    if (_profileModalOpenClientId) {
                        const refreshId = _profileModalOpenClientId;
                        await loadClients();
                        await openProfileModal(refreshId);
                    }
                } else {
                    showError('Erro ao salvar atividade');
                }
            } catch (error) {
                showError('Erro ao salvar atividade: ' + error.message);
            }
        }

        // Edit Activity
        async function editActivity(id) {
            const activity = activities.find(a => a.id === id);
            if (activity) {
                currentEditingActivityId = id;
                document.getElementById('activityModalTitle').textContent = 'Editar Atividade';
                await loadClientSelect(activity.company || '');
                document.getElementById('clientSelect').value = activity.client_id;
                document.getElementById('activityForm').contact_type.value = activity.contact_type || 'Outro';
                document.getElementById('activityForm').information.value = activity.information || '';
                document.getElementById('activityModal').classList.add('active');
            }
        }

        // Delete Activity
        async function deleteActivity(id) {
            if (await uiConfirm('Tem certeza que deseja deletar esta atividade?')) {
                try {
                    const response = await fetch(`${API_BASE}/atividades/${id}`, {
                        method: 'DELETE'
                    });

                    if (response.ok) {
                        showSuccess('Atividade deletada!');
                        loadActivities();
                        loadDashboard();
                    } else {
                        showError('Erro ao deletar atividade');
                    }
                } catch (error) {
                    showError('Erro ao deletar atividade');
                }
            }
        }

        // Export Clients
        async function exportClients() {
            openClientExportModal();
        }

        async function confirmClientExport() {
            const selectedFields = getSelectedClientExportFields();
            if (selectedFields.length === 0) {
                showError('Selecione ao menos um campo para exportar.');
                return;
            }

            try {
                const query = encodeURIComponent(selectedFields.join(','));
                const response = await fetch(`${API_BASE}/export/clientes?fields=${query}`);
                if (!response.ok) {
                    throw new Error('Erro ao exportar clientes');
                }
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `clientes_${new Date().toISOString().split('T')[0]}.csv`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                closeClientExportModal();
            } catch (error) {
                showError('Erro ao exportar clientes');
            }
        }

        // Export Activities
        async function exportActivities() {
            const startDate = document.getElementById('startDate').value;
            const endDate = document.getElementById('endDate').value;

            if (!startDate || !endDate) {
                showError('Selecione as datas de início e fim');
                return;
            }

            try {
                const response = await fetch(`${API_BASE}/export/atividades?start_date=${startDate}&end_date=${endDate}`);
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `atividades_${startDate}_${endDate}.csv`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
            } catch (error) {
                showError('Erro ao exportar atividades');
            }
        }

        // Backup Database
        async function backupDatabase() {
            try {
                const includeImages = await uiConfirm(
                    'Deseja incluir também as imagens (contatos, contas, perfil e arquivos em uploads) no backup? Se sim, o arquivo será exportado em .zip.',
                    'Exportar Banco'
                );
                const endpoint = includeImages ? `${API_BASE}/backup/database?include_uploads=true` : `${API_BASE}/backup/database`;
                const response = await fetch(endpoint);
                if (!response.ok) throw new Error('Erro ao fazer backup');
                
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5);
                a.download = includeImages
                    ? `toca-do-coelho-backup-${timestamp}.zip`
                    : `toca-do-coelho-backup-${timestamp}.db`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                showSuccess(includeImages
                    ? 'Backup completo (banco + imagens) realizado com sucesso!'
                    : 'Backup do banco de dados realizado com sucesso!');
            } catch (error) {
                showError('Erro ao fazer backup do banco de dados');
            }
        }

        // Restore Database
        async function restoreDatabase(event) {
            const file = event.target.files[0];
            if (!file) return;
            const lowerName = (file.name || '').toLowerCase();
            const isZip = lowerName.endsWith('.zip');
            const mergeMode = await uiConfirm(
                'Escolha o modo de importação:\n\nOK = Fundir bancos (recomendado, não apaga dados atuais).\nCancelar = Substituir tudo (restauração completa).',
                'Importar Banco'
            );
            const importMode = mergeMode ? 'merge' : 'replace_all';
            
            if (!lowerName.endsWith('.db') && !lowerName.endsWith('.zip')) {
                showError('Por favor, selecione um arquivo .db ou .zip válido');
                return;
            }

            if (!isZip) {
                const continueDbOnly = await uiConfirm(
                    'Você selecionou um arquivo .db (somente banco). As imagens não serão restauradas. Para manter cards e fotos exatamente como estavam, use um backup .zip completo. Deseja continuar mesmo assim?',
                    'Importar somente banco'
                );
                if (!continueDbOnly) {
                    event.target.value = '';
                    return;
                }
            }
            
            if (importMode === 'replace_all') {
                if (!await uiConfirm('ATENÇÃO: Isso irá substituir o banco de dados atual. Um backup automático será criado antes. Deseja continuar?', 'Atenção')) {
                    event.target.value = '';
                    return;
                }
            } else {
                if (!await uiConfirm('Você escolheu FUNDIR bancos. O sistema vai comparar por Nome, depois Email e depois Telefone. Deseja continuar?', 'Confirmar fusão')) {
                    event.target.value = '';
                    return;
                }
            }
            
            try {
                const formData = new FormData();
                formData.append('file', file);
                formData.append('mode', importMode);
                
                const response = await fetch(`${API_BASE}/restore/database`, {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (!response.ok) {
                    throw new Error(result.error || 'Erro ao restaurar banco');
                }
                
                if (result.mode === 'merge') {
                    const s = result.merge_summary || {};
                    showSuccess(
                        `${result.message} Processadas: ${s.processed || 0}, novas: ${s.imported || 0}, atualizadas: ${s.updated || 0}, conflitos ignorados: ${s.conflicts || 0}.`
                    );
                } else {
                    showSuccess(result.message);
                    
                    // Recarregar a página após 2 segundos
                    setTimeout(() => {
                        window.location.reload();
                    }, 2000);
                }
                
            } catch (error) {
                showError(error.message || 'Erro ao restaurar banco de dados');
            } finally {
                event.target.value = '';
            }
        }

        function monthRange(dateObj) {
            const start = new Date(dateObj.getFullYear(), dateObj.getMonth(), 1);
            const end = new Date(dateObj.getFullYear(), dateObj.getMonth() + 1, 0);
            return { start, end };
        }

        async function loadKanban() {
            try {
                const [colsRes, cardsRes, accountsRes, contactsRes] = await Promise.all([
                    fetch(`${API_BASE}/kanban/columns`),
                    fetch(`${API_BASE}/kanban/cards`),
                    fetch(`${API_BASE}/accounts`),
                    fetch(`${API_BASE}/clients`)
                ]);
                kanbanColumns = await colsRes.json();
                kanbanCards = await cardsRes.json();
                kanbanAccounts = accountsRes.ok ? await accountsRes.json() : [];
                kanbanContacts = contactsRes.ok ? await contactsRes.json() : [];
                renderKanban();
            } catch (e) {
                console.error(e);
                showError('Erro ao carregar o Kanban');
            }
        }

        function parseKanbanTags(tagString) {
            return (tagString || '').split('|').map(t => t.trim()).filter(Boolean);
        }

        function extractKanbanKeywords(text) {
            const t = (text || '').toLowerCase();
            const tokens = t.match(/[a-zà-ÿ0-9]{3,}/g) || [];
            const stop = new Set(['para','com','sobre','entre','pelos','pelas','isso','essa','esse','dele','dela','card','tarefa','atividade','fazer','sera','será','esta','está','mais','muito','pouco','uma','uns','das','dos','que','por','sem']);
            const out = [];
            for (const token of tokens) {
                if (stop.has(token)) continue;
                const label = token.charAt(0).toUpperCase() + token.slice(1);
                if (!out.includes(label)) out.push(label);
                if (out.length >= 4) break;
            }
            return out;
        }

        function countBusinessDaysSince(dateLike) {
            if (!dateLike) return 0;
            const start = new Date(dateLike);
            if (Number.isNaN(start.getTime())) return 0;
            const end = new Date();
            start.setHours(0, 0, 0, 0);
            end.setHours(0, 0, 0, 0);
            let count = 0;
            const cur = new Date(start);
            while (cur < end) {
                cur.setDate(cur.getDate() + 1);
                const day = cur.getDay();
                if (day !== 0 && day !== 6) count += 1;
            }
            return count;
        }

        function isKanbanCardOverdue(card) {
            const urgency = String(card.urgency || 'Média');
            const limits = { 'Baixa': 5, 'Média': 3, 'Alta': 2, 'Crítica': 1 };
            const limit = limits[urgency] ?? 3;
            const refDate = card.last_activity_at || card.updated_at || card.created_at;
            return countBusinessDaysSince(refDate) >= limit;
        }

        function renderKanban() {
            const board = document.getElementById('kanbanBoard');
            if (!board) return;
            const cardsByColumn = {};
            kanbanColumns.forEach(col => cardsByColumn[col.id] = []);
            kanbanCards.forEach(card => {
                if (!cardsByColumn[card.column_id]) cardsByColumn[card.column_id] = [];
                cardsByColumn[card.column_id].push(card);
            });

            board.innerHTML = kanbanColumns.map(column => {
                const locked = Number(column.is_locked) === 1;
                const normalizedTitle = String(column.title || '').toLowerCase();
                const isDiscardedColumn = normalizedTitle === 'descartado';
                const isDoneColumn = normalizedTitle === 'done';
                const actionButtons = locked ? '' : `
                    <div style="display:flex; gap:4px;">
                        <button class="btn btn-edit-accent btn-small" onclick="renameKanbanColumn(${column.id}, '${escapeHtml(column.title).replace(/'/g, "\\'")}')"><i class="fas fa-pen"></i></button>
                        <button class="btn btn-danger btn-small" onclick="deleteKanbanColumn(${column.id})"><i class="fas fa-trash"></i></button>
                    </div>`;
                const cardsInColumn = (cardsByColumn[column.id] || []);
                const cardsHtml = cardsInColumn.map((card, idx) => {
                    const accountImg = card.account_logo_url || '/logo-coelho.png';
                    const contactImg = card.contact_photo_url || '/images/sad-contact-bunny.svg';
                    const resolvedTags = parseKanbanTags(card.tag).length ? parseKanbanTags(card.tag) : extractKanbanKeywords(card.description || '');
                    const tagsHtml = resolvedTags.map(tag => `<span class="kanban-tag">${escapeHtml(tag)}</span>`).join('');
                    const stateClass = isDiscardedColumn ? 'kanban-card-discarded' : (isDoneColumn ? 'kanban-card-done' : '');
                    return `<div class="kanban-card ${stateClass}" data-card-id="${card.id}" onclick="onKanbanCardClick(event, ${card.id})">
                        <div style="display:flex; justify-content:space-between; gap:8px;">
                            <h4>${escapeHtml(card.title)}</h4>
                            <div class="kanban-card-actions">
                                <button class="btn btn-edit-accent btn-small kanban-card-action-btn" onclick="event.stopPropagation(); openKanbanCardModal(${card.id})"><i class="fas fa-pen"></i></button>
                                <button class="btn btn-danger btn-small kanban-card-action-btn" onclick="event.stopPropagation(); deleteKanbanCard(${card.id})"><i class="fas fa-trash"></i></button>
                            </div>
                        </div>
                        ${card.account_name ? `<div class="kanban-meta"><img src="${accountImg}" class="kanban-avatar"> ${escapeHtml(card.account_name)}</div>` : ''}
                        ${card.contact_name ? `<div class="kanban-meta"><img src="${contactImg}" class="kanban-avatar"> ${escapeHtml(card.contact_name)}</div>` : ''}
                        ${tagsHtml ? `<div class="kanban-tags">${tagsHtml}</div>` : ''}
                        ${isKanbanCardOverdue(card) ? `<span class="kanban-urgent-badge" title="Sem update de atividade no prazo">!</span>` : ''}
                        <span class="kanban-urgency-chip" onclick="event.stopPropagation(); openKanbanUrgencyEditor(event, ${card.id}, '${(card.urgency || 'Média').replace(/'/g, "\\'")}')">${escapeHtml(card.urgency || 'Média')}</span>
                    </div>`;
                }).join('');
                return `<div class="kanban-column" data-column-id="${column.id}" data-column-locked="${locked ? 1 : 0}">
                    <div class="kanban-column-head">
                        <span class="kanban-column-title">${escapeHtml(column.title)}</span>
                        ${actionButtons}
                    </div>
                    <div class="kanban-cards">${cardsHtml}</div>
                </div>`;
            }).join('');
            initKanbanSortable();
        }

        function createKanbanColumn() {
            const title = prompt('Nome da sessão:');
            if (!title) return;
            fetch(`${API_BASE}/kanban/columns`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title })
            }).then(async res => {
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Erro ao criar sessão');
                showSuccess('Sessão criada com sucesso');
                loadKanban();
            }).catch(err => showError(err.message));
        }

        function renameKanbanColumn(columnId, currentTitle) {
            const title = prompt('Novo nome da sessão:', currentTitle || '');
            if (!title) return;
            fetch(`${API_BASE}/kanban/columns/${columnId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title })
            }).then(async res => {
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Erro ao editar sessão');
                showSuccess('Sessão atualizada');
                loadKanban();
            }).catch(err => showError(err.message));
        }

        async function deleteKanbanColumn(columnId) {
            if (!await uiConfirm('Excluir sessão? Cards serão movidos para o Backlog.', 'Excluir Sessão')) return;
            fetch(`${API_BASE}/kanban/columns/${columnId}`, { method: 'DELETE' })
                .then(async res => {
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.error || 'Erro ao apagar sessão');
                    showSuccess('Sessão removida');
                    loadKanban();
                }).catch(err => showError(err.message));
        }

        function renderKanbanContactOptions(selectedAccountId, selectedContactId = '') {
            const contactSelect = document.getElementById('kanbanCardContact');
            if (!contactSelect) return;
            let filtered = kanbanContacts;
            if (selectedAccountId) {
                const account = kanbanAccounts.find(a => Number(a.id) === Number(selectedAccountId));
                const accountName = (account?.name || '').trim().toLowerCase();
                filtered = kanbanContacts.filter(c => (c.company || '').trim().toLowerCase() === accountName);
            }
            contactSelect.innerHTML = `<option value="">Selecione</option>${filtered.map(c => `<option value="${c.id}">${escapeHtml(c.name)} (${escapeHtml(c.position || 'Sem cargo')})</option>`).join('')}`;
            contactSelect.value = selectedContactId || '';
        }

        function openKanbanCardModal(cardId = null) {
            const modal = document.getElementById('kanbanCardModal');
            const form = document.getElementById('kanbanCardForm');
            form.reset();
            document.getElementById('kanbanCardId').value = cardId || '';
            document.getElementById('kanbanCardModalTitle').textContent = cardId ? 'Editar card' : 'Novo card';

            const accountSelect = document.getElementById('kanbanCardAccount');
            accountSelect.innerHTML = `<option value="">Selecione</option>${kanbanAccounts.map(a => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join('')}`;

            let selectedAccountId = '';
            let selectedContactId = '';

            if (cardId) {
                const card = kanbanCards.find(c => c.id === cardId);
                if (card) {
                    document.getElementById('kanbanCardTitle').value = card.title || '';
                    document.getElementById('kanbanCardDescription').value = card.description || '';
                    document.getElementById('kanbanCardTag').value = card.tag || '';
                    selectedAccountId = card.account_id || '';
                    selectedContactId = card.contact_id || '';
                    document.getElementById('kanbanCardUrgency').value = card.urgency || 'Média';
                }
            }
            if (!cardId) document.getElementById('kanbanCardUrgency').value = 'Média';
            accountSelect.value = selectedAccountId;
            renderKanbanContactOptions(selectedAccountId, selectedContactId);
            accountSelect.onchange = () => renderKanbanContactOptions(accountSelect.value, '');

            modal.classList.add('active');
        }

        function closeKanbanCardModal() {
            const modal = document.getElementById('kanbanCardModal');
            if (modal) modal.classList.remove('active');
        }

        function inferKanbanTagLocal(text) {
            const t = (text || '').toLowerCase();
            if (!t) return '';
            const tags = [];
            if (['proposta', 'negoci', 'cliente', 'venda', 'lead'].some(k => t.includes(k))) tags.push('Comercial');
            if (['api', 'erro', 'deploy', 'bug', 'infra', 'arquitetura'].some(k => t.includes(k))) tags.push('Técnico');
            if (['fatur', 'pagamento', 'budget', 'contrato', 'receita'].some(k => t.includes(k))) tags.push('Financeiro');
            if (['reuniao', 'follow-up', 'contato', 'feedback', 'stakeholder'].some(k => t.includes(k))) tags.push('Relacionamento');
            if (['produto', 'feature', 'roadmap', 'release', 'sprint'].some(k => t.includes(k))) tags.push('Produto');
            if (['urgente', 'critico', 'hoje', 'bloqueio'].some(k => t.includes(k))) tags.push('Prioridade Alta');
            const derived = extractKanbanKeywords(t);
            return tags.join(' | ') || derived.join(' | ');
        }

        function autoFillKanbanTag() {
            const desc = document.getElementById('kanbanCardDescription')?.value || '';
            const tagInput = document.getElementById('kanbanCardTag');
            if (!tagInput) return;
            if ((tagInput.value || '').trim()) return;
            tagInput.value = inferKanbanTagLocal(desc);
        }

        async function saveKanbanCard(event) {
            event.preventDefault();
            const cardId = document.getElementById('kanbanCardId').value;
            const payload = {
                title: document.getElementById('kanbanCardTitle').value.trim(),
                description: document.getElementById('kanbanCardDescription').value.trim(),
                tag: document.getElementById('kanbanCardTag').value.trim(),
                account_id: document.getElementById('kanbanCardAccount').value || null,
                contact_id: document.getElementById('kanbanCardContact').value || null,
                urgency: document.getElementById('kanbanCardUrgency').value
            };
            const endpoint = cardId ? `${API_BASE}/kanban/cards/${cardId}` : `${API_BASE}/kanban/cards`;
            const method = cardId ? 'PUT' : 'POST';
            try {
                const response = await fetch(endpoint, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || 'Erro ao salvar card');
                closeKanbanCardModal();
                showSuccess(cardId ? 'Card atualizado' : 'Card criado');
                loadKanban();
            } catch (e) {
                showError(e.message);
            }
        }

        async function openKanbanCardViewModal(cardId) {
            try {
                const response = await fetch(`${API_BASE}/kanban/cards/${cardId}`);
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || 'Erro ao abrir card');
                const resolvedTags = parseKanbanTags(data.tag).length ? parseKanbanTags(data.tag) : extractKanbanKeywords(data.description || '');
                const tagsHtml = resolvedTags.map(tag => `<span class=\"kanban-tag\">${escapeHtml(tag)}</span>`).join('');
                const activities = data.activities || [];
                document.getElementById('kanbanCardViewTitle').textContent = data.title || 'Card';
                const accountBlock = data.account_name
                    ? `<div class="kanban-view-box"><div style="color:#6b7280;font-size:12px;">Conta</div><div style="display:flex; align-items:center; gap:8px; margin-top:4px;"><img src="${data.account_logo_url || '/logo-coelho.png'}" class="kanban-avatar"><div style="font-weight:700;color:#065f46;">${escapeHtml(data.account_name)}</div></div></div>`
                    : `<div class="kanban-view-box"><div style="color:#6b7280;font-size:12px;">Conta</div><div style="font-weight:700;color:#94a3b8;">Não vinculada</div></div>`;
                const contactBlock = data.contact_name
                    ? `<div style="display:flex; align-items:center; gap:8px;"><img src="${data.contact_photo_url || '/images/sad-contact-bunny.svg'}" class="kanban-avatar"><div><div style="font-weight:700;color:#065f46;">${escapeHtml(data.contact_name)}</div><div style="font-size:11px;color:#94a3b8;">${escapeHtml(data.contact_position || '')}</div></div></div>`
                    : '<div style="font-weight:700;color:#94a3b8;">Não vinculado</div>';
                document.getElementById('kanbanCardViewBody').innerHTML = `
                    <div class="kanban-view-grid">
                        <div class="kanban-view-box"><div style="color:#6b7280;font-size:12px;">Sessão</div><div style="font-weight:700;color:#065f46;">${escapeHtml(data.column_title || '-')}</div></div>
                        ${accountBlock}
                    </div>
                    <div class="kanban-view-box" style="margin-bottom:12px;"><div style="display:flex;justify-content:space-between;align-items:center;gap:8px;"><div style="color:#6b7280;font-size:12px; margin-bottom:4px;">Descrição</div><span class="kanban-tag">Urgência: ${escapeHtml(data.urgency || 'Média')}</span></div><div style="white-space:pre-wrap; color:#334155;">${escapeHtml(data.description || '')}</div></div>
                    <div class="kanban-view-inline-meta">
                        <div class="kanban-view-box"><div style="color:#6b7280;font-size:12px; margin-bottom:4px;">Tags</div><div class="kanban-tags" style="margin-top:0;">${tagsHtml || ''}</div></div>
                        <div class="kanban-view-box"><div style="color:#6b7280;font-size:12px; margin-bottom:4px;">Contato</div>${contactBlock}</div>
                    </div>
                    <div class="kanban-view-box" style="margin-bottom:12px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;"><strong style="color:#065f46;">Atividades</strong></div>
                        <form onsubmit="saveKanbanCardActivity(event, ${data.id})" style="display:flex; gap:8px; margin-bottom:10px;">
                            <input id="kanbanActivityInput" placeholder="Adicionar atividade..." style="flex:1;" required>
                            <button class="btn btn-primary btn-small" type="submit">Adicionar</button>
                        </form>
                        <div id="kanbanActivityHistory">${activities.map(a => `<div class="kanban-activity-item"><div style="font-size:12px;color:#9ca3af;margin-bottom:4px;">${new Date(a.created_at).toLocaleString('pt-BR')}</div><div>${escapeHtml(a.content)}</div></div>`).join('') || '<div style="color:#9ca3af;">Sem atividades registradas.</div>'}</div>
                    </div>
                    <div style="display:flex; justify-content:flex-end; gap:8px;"><button class="btn btn-edit-accent" onclick="closeKanbanCardViewModal(); openKanbanCardModal(${data.id})"><i class="fas fa-pen"></i> Editar</button></div>
                `;
                document.getElementById('kanbanCardViewModal').classList.add('active');
            } catch (e) {
                showError(e.message);
            }
        }

        async function saveKanbanCardActivity(event, cardId) {
            event.preventDefault();
            const input = document.getElementById('kanbanActivityInput');
            const content = (input?.value || '').trim();
            if (!content) return;
            try {
                const response = await fetch(`${API_BASE}/kanban/cards/${cardId}/activities`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content })
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || 'Erro ao salvar atividade');
                input.value = '';
                openKanbanCardViewModal(cardId);
                loadKanban();
            } catch (e) {
                showError(e.message);
            }
        }

        function closeKanbanCardViewModal() {
            const modal = document.getElementById('kanbanCardViewModal');
            if (modal) modal.classList.remove('active');
        }

        document.addEventListener('click', (ev) => {
            const editor = document.getElementById('kanbanUrgencyEditor');
            if (!editor || !editor.classList.contains('open')) return;
            if (ev.target.closest('#kanbanUrgencyEditor') || ev.target.closest('.kanban-urgency-chip')) return;
            closeKanbanUrgencyEditor();
        });


        function closeKanbanUrgencyEditor() {
            const editor = document.getElementById('kanbanUrgencyEditor');
            if (!editor) return;
            editor.classList.remove('open');
            editor.innerHTML = '';
        }

        function openKanbanUrgencyEditor(event, cardId, currentUrgency) {
            const editor = document.getElementById('kanbanUrgencyEditor');
            if (!editor) return;
            const options = ['Baixa', 'Média', 'Alta', 'Crítica'];
            editor.innerHTML = options.map(opt => `<button onclick="setKanbanCardUrgency(${cardId}, '${opt}')">${opt}${opt===currentUrgency?' ✓':''}</button>`).join('');
            editor.style.left = `${(event.clientX || 0) + 8}px`;
            editor.style.top = `${(event.clientY || 0) - 8}px`;
            editor.classList.add('open');
        }

        async function setKanbanCardUrgency(cardId, urgency) {
            try {
                const response = await fetch(`${API_BASE}/kanban/cards/${cardId}/urgency`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ urgency })
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || 'Erro ao atualizar urgência');
                closeKanbanUrgencyEditor();
                loadKanban();
            } catch (e) {
                showError(e.message);
            }
        }

        async function deleteKanbanCard(cardId) {
            const confirmed = await uiConfirm('Deseja excluir este card? Esta ação não pode ser desfeita.', 'Excluir card');
            if (!confirmed) return;
            try {
                const response = await fetch(`${API_BASE}/kanban/cards/${cardId}`, { method: 'DELETE' });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || 'Erro ao excluir card');
                showSuccess('Card removido');
                loadKanban();
            } catch (e) {
                showError(e.message);
            }
        }

        function onKanbanCardClick(event, cardId) {
            if (Date.now() - Number(kanbanDragState.movedAt || 0) < 250) return;
            openKanbanCardViewModal(cardId);
        }
        function isKanbanDevMode() {
            const host = String(window.location?.hostname || '').toLowerCase();
            return host === 'localhost' || host === '127.0.0.1' || host.endsWith('.local');
        }

        function logKanbanDrag(eventName, payload = {}) {
            if (!isKanbanDevMode()) return;
            console.debug(`[kanban_dnd] ${eventName}`, payload);
        }

        function cloneKanbanCardsState() {
            return (kanbanCards || []).map(card => ({ ...card }));
        }

        function applyKanbanMoveLocally(cardId, fromColumnId, toColumnId, newIndex) {
            const nextCards = cloneKanbanCardsState();
            const cardIndex = nextCards.findIndex(card => Number(card.id) === Number(cardId));
            if (cardIndex < 0) return false;
            const [movingCard] = nextCards.splice(cardIndex, 1);
            const sourceCards = nextCards.filter(card => Number(card.column_id) === Number(fromColumnId));
            const targetCards = Number(fromColumnId) === Number(toColumnId)
                ? sourceCards
                : nextCards.filter(card => Number(card.column_id) === Number(toColumnId));
            const boundedIndex = Math.max(0, Math.min(Number(newIndex) || 0, targetCards.length));
            movingCard.column_id = Number(toColumnId);
            targetCards.splice(boundedIndex, 0, movingCard);

            const rebuilt = [];
            kanbanColumns.forEach(column => {
                if (Number(column.id) === Number(fromColumnId) && Number(fromColumnId) !== Number(toColumnId)) {
                    rebuilt.push(...sourceCards);
                    return;
                }
                if (Number(column.id) === Number(toColumnId)) {
                    rebuilt.push(...targetCards);
                    return;
                }
                rebuilt.push(...nextCards.filter(card => Number(card.column_id) === Number(column.id)));
            });
            kanbanCards = rebuilt;
            return true;
        }

        async function persistKanbanMove(cardId, columnId, position) {
            const startedAt = performance.now();
            const response = await fetch(`${API_BASE}/kanban/cards/${cardId}/move`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ column_id: Number(columnId), position: Number(position) })
            });
            const elapsedMs = Math.round(performance.now() - startedAt);
            const data = await response.json();
            if (!response.ok) {
                logKanbanDrag('persist_error', { cardId, columnId, position, elapsedMs, error: data.error || 'Erro ao mover card' });
                throw new Error(data.error || 'Erro ao mover card');
            }
            logKanbanDrag('persist_success', { cardId, columnId, position, elapsedMs });
            return data;
        }

        function destroyKanbanSortableInstances() {
            kanbanSortableInstances.forEach(instance => instance.destroy());
            kanbanSortableInstances.clear();
        }

        function initKanbanSortable() {
            destroyKanbanSortableInstances();
            if (typeof Sortable === 'undefined') {
                console.warn('SortableJS não carregado; DnD do Kanban desativado.');
                return;
            }
            const columns = Array.from(document.querySelectorAll('.kanban-column[data-column-id]'));
            columns.forEach(columnEl => {
                const cardsContainer = columnEl.querySelector('.kanban-cards');
                if (!cardsContainer) return;
                const columnId = Number(columnEl.getAttribute('data-column-id'));
                // Drag liberado em todas as colunas — is_locked só bloqueia edição/exclusão da coluna
                const sortable = Sortable.create(cardsContainer, {
                    group: { name: 'kanban', pull: true, put: true },
                    sort: true,
                    animation: 150,
                    emptyInsertThreshold: 20,
                    ghostClass: 'sortable-ghost',
                    dragClass: 'sortable-drag',
                    chosenClass: 'sortable-chosen',
                    filter: '.kanban-card-action-btn, .kanban-urgency-chip, button, a, input, textarea, select',
                    preventOnFilter: false,
                    onStart: (evt) => {
                        kanbanDragState.sorting = true;
                        kanbanDragState.movedAt = Date.now();
                        document.querySelector('.kanban-board')?.classList.add('kanban-dragging');
                        logKanbanDrag('drag_start', { cardId: Number(evt.item?.getAttribute('data-card-id')), fromColumnId: columnId });
                    },
                    onMove: (evt) => {
                        document.querySelectorAll('.kanban-cards.sortable-over')
                            .forEach(el => el.classList.remove('sortable-over'));
                        if (evt.to && evt.to !== evt.from) evt.to.classList.add('sortable-over');
                        return true;
                    },
                    onEnd: async (evt) => {
                        document.querySelectorAll('.kanban-cards.sortable-over')
                            .forEach(el => el.classList.remove('sortable-over'));
                        document.querySelector('.kanban-board')?.classList.remove('kanban-dragging');
                        kanbanDragState.sorting = false;
                        kanbanDragState.movedAt = Date.now();
                        const cardId = Number(evt.item?.getAttribute('data-card-id'));
                        const fromColumnId = Number(evt.from?.closest('.kanban-column')?.getAttribute('data-column-id'));
                        const toColumnId = Number(evt.to?.closest('.kanban-column')?.getAttribute('data-column-id'));
                        const oldIndex = Number(evt.oldIndex);
                        const newIndex = Number(evt.newIndex);
                        logKanbanDrag('drag_end', { cardId, fromColumnId, toColumnId, oldIndex, newIndex });
                        if (!cardId || Number.isNaN(newIndex) || Number.isNaN(toColumnId) || Number.isNaN(fromColumnId)) return;
                        if (fromColumnId === toColumnId && oldIndex === newIndex) return;
                        if (kanbanDragState.requestInFlight) {
                            const cards = Array.from(evt.from?.querySelectorAll('.kanban-card') || []);
                            const target = cards[oldIndex] || null;
                            if (target) evt.from.insertBefore(evt.item, target);
                            else evt.from.appendChild(evt.item);
                            if (evt.from !== evt.to) evt.to?.classList.remove('sortable-over');
                            showError('Aguarde a conclusão do movimento anterior.');
                            return;
                        }
                        const localSnapshot = cloneKanbanCardsState();
                        kanbanDragState.snapshot = localSnapshot;
                        if (!applyKanbanMoveLocally(cardId, fromColumnId, toColumnId, newIndex)) {
                            kanbanDragState.snapshot = null;
                            return;
                        }
                        try {
                            kanbanDragState.requestInFlight = true;
                            await persistKanbanMove(cardId, toColumnId, newIndex);
                            kanbanDragState.snapshot = null;
                        } catch (e) {
                            if (localSnapshot) kanbanCards = localSnapshot;
                            kanbanDragState.snapshot = null;
                            kanbanDragState.rollbackCount = Number(kanbanDragState.rollbackCount || 0) + 1;
                            renderKanban();
                            showError(e.message);
                        } finally {
                            kanbanDragState.requestInFlight = false;
                        }
                    }
                });
                kanbanSortableInstances.set(columnId, sortable);
            });
        }

        // Mapeamento de Ambiente
        let mappingCards = [];
        let mappingSelectedClient = null;
        let mappingAccounts = [];

        async function loadMapeamento() {
            try {
                // Salvar seleção atual antes de recarregar
                const filterSelect = document.getElementById('mappingClientFilter');
                const previousSelection = filterSelect ? filterSelect.value : '';
                
                // Carregar cards
                const cardsResponse = await fetch(`${API_BASE}/environment/cards`);
                mappingCards = await cardsResponse.json();

                // Carregar contas cadastradas e clientes
                const [accountsResponse, clientsResponse] = await Promise.all([
                    fetch(`${API_BASE}/accounts`),
                    fetch(`${API_BASE}/clientes`)
                ]);
                mappingAccounts = await accountsResponse.json();
                const clientsList = await clientsResponse.json();

                // Preencher dropdown com contas
                filterSelect.innerHTML = '<option value="">Selecione uma conta</option>';

                // Mapeamento conta(empresa) -> client_id (quando existir cliente vinculado)
                const accountClientMap = new Map();
                clientsList.forEach(client => {
                    if (client.company && !accountClientMap.has(client.company)) {
                        accountClientMap.set(client.company, client.id);
                    }
                });

                const sortedAccounts = (mappingAccounts || [])
                    .slice()
                    .sort((a, b) => (a.name || '').localeCompare((b.name || ''), 'pt-BR'));

                sortedAccounts.forEach((account) => {
                    const option = document.createElement('option');
                    option.value = String(account.id);
                    option.textContent = account.name || `Conta ${account.id}`;
                    if (!accountClientMap.has(account.name)) {
                        option.title = 'Sem cliente vinculado para respostas';
                    }
                    filterSelect.appendChild(option);
                });

                // Restaurar seleção anterior
                if (previousSelection) {
                    filterSelect.value = previousSelection;
                }

                // Obter cliente selecionado a partir da conta escolhida
                const selectedAccountId = parseInt(filterSelect.value || '', 10);
                const selectedAccount = (mappingAccounts || []).find(a => Number(a.id) === selectedAccountId);
                const selectedCompany = selectedAccount && selectedAccount.name ? selectedAccount.name : '';
                mappingSelectedClient = selectedCompany && accountClientMap.has(selectedCompany)
                    ? parseInt(accountClientMap.get(selectedCompany), 10)
                    : null;

                // Exibir botão Auto-preencher somente quando há conta selecionada
                const _autoFillBtn = document.getElementById('envAutoFillBtn');
                if (_autoFillBtn) _autoFillBtn.style.display = selectedAccountId ? '' : 'none';

                // Renderizar cards
                await renderMappingCards();
                await loadAutoMappingQueriesHistory();
            } catch (error) {
                showError('Erro ao carregar mapeamento de ambiente');
            }
        }

        async function renderMappingCards() {
            const content = document.getElementById('mapeamentoContent');
            let html = '<div class="mapping-cards-grid">';

            for (const card of mappingCards) {
                html += `<div class="mapping-card" onclick="openMappingCardModal(${card.id})">`;
                html += `<button class="mapping-card-edit-btn" onclick="event.stopPropagation(); editMappingCard(${card.id})" title="Editar Card"><i class="fas fa-edit"></i></button>`;
                html += `<button class="mapping-card-delete-btn" onclick="event.stopPropagation(); deleteMappingCard(${card.id})" title="Deletar Card"><i class="fas fa-trash"></i></button>`;
                html += `<div class="mapping-card-title">${escapeHtml(card.title)}</div>`;
                html += `<div class="mapping-card-description">${escapeHtml(card.description || 'Sem descrição')}</div>`;

                // Se um cliente está selecionado, mostrar a resposta inline
                if (mappingSelectedClient) {
                    const response = await getMappingResponse(card.id, mappingSelectedClient);
                    html += '<div class="mapping-response-inline">';
                    if (response && response.response) {
                        html += `<div class="mapping-response-text">${escapeHtml(response.response)}</div>`;
                    } else {
                        html += '<div class="mapping-response-empty">Nenhuma resposta cadastrada</div>';
                    }
                    html += '</div>';
                }

                html += '</div>';
            }

            html += '</div>';
            content.innerHTML = html;
        }

        function toggleAutoMappingRunDetails(runId) {
            const panel = document.getElementById(`autoMapRunDetails_${runId}`);
            const icon = document.getElementById(`autoMapRunIcon_${runId}`);
            if (!panel) return;
            const isHidden = panel.style.display === 'none' || !panel.style.display;
            panel.style.display = isHidden ? 'block' : 'none';
            if (icon) icon.textContent = isHidden ? '▾' : '▸';
        }

        async function deleteAutoMappingRun(runId, triggerEl) {
            const confirmed = await uiConfirm('Deseja realmente excluir este log do AutoMapping?', 'Excluir Log');
            if (!confirmed) return;
            try {
                const response = await fetch(`${API_BASE}/automapping/runs/${runId}`, { method: 'DELETE' });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || 'Falha ao excluir log');
                showSuccess('Log de AutoMapping excluído.');
                await loadAutoMappingQueriesHistory();
            } catch (error) {
                showError(`Não foi possível excluir o log: ${error.message}`);
            }
        }

        async function loadAutoMappingQueriesHistory() {
            const container = document.getElementById('autoMappingQueriesSection');
            if (!container) return;
            try {
                const response = await fetch(`${API_BASE}/automapping/runs?days=20`);
                const payload = await response.json();
                const runs = payload.runs || [];
                autoMappingRunsHistory = runs;
                if (!runs.length) {
                    container.innerHTML = `
                        <div class="automapping-result-card" style="background:#fff; border-color:#e5e7eb;">
                            <h3 style="margin:0; color:#1f2937;">Consultas do AutoMapping (últimos 20 dias)</h3>
                            <p style="margin-top:8px; color:#6b7280; font-size:13px;">Nenhuma execução encontrada.</p>
                        </div>
                    `;
                    return;
                }

                let html = `
                    <div class="automapping-result-card" style="background:#fff; border-color:#e5e7eb;">
                        <h3 style="margin:0 0 10px; color:#1f2937;">Consultas do AutoMapping (últimos 20 dias)</h3>
                        <div style="display:flex; flex-direction:column; gap:10px; max-height:320px; overflow:auto;">
                `;

                runs.forEach(run => {
                    const queriesEntries = Object.entries(run.queries || {});
                    html += `<div style="border:1px solid #e5e7eb; border-radius:10px; padding:10px; cursor:pointer;" onclick="openExistingAutoMappingRun(${run.id})">`;
                    html += `<div style="display:flex; justify-content:space-between; gap:8px; align-items:center;">`;
                    html += `<button type="button" onclick="event.stopPropagation(); toggleAutoMappingRunDetails(${run.id})" style="background:transparent; border:none; text-align:left; cursor:pointer; flex:1;">`;
                    html += `<div style="font-size:13px; color:#111827; font-weight:600;"><span id="autoMapRunIcon_${run.id}">▸</span> ${escapeHtml(run.company || '-')} · ${escapeHtml(run.country || '-')} · ${escapeHtml(run.industry || '-')}</div>`;
                    html += `<div style="font-size:11px; color:#6b7280; margin-top:2px;">Execução: ${escapeHtml(run.created_at || '-')} · ${queriesEntries.length} queries</div>`;
                    html += `</button>`;
                    html += `<button class="btn btn-danger btn-small" onclick="event.stopPropagation(); deleteAutoMappingRun(${run.id}, this)" title="Excluir log"><i class="fas fa-trash"></i></button>`;
                    html += `</div>`;
                    html += `<div id="autoMapRunDetails_${run.id}" style="display:none; margin-top:8px;">`;
                    if (!queriesEntries.length) {
                        html += `<div style="font-size:12px; color:#9ca3af;">Sem queries registradas.</div>`;
                    } else {
                        html += `<div style="display:flex; flex-direction:column; gap:4px;">`;
                        queriesEntries.forEach(([section, query]) => {
                            html += `<div style="font-size:12px; color:#374151;"><strong>${escapeHtml(section)}:</strong> ${escapeHtml(query)}</div>`;
                        });
                        html += `</div>`;
                    }
                    html += `</div>`;
                    html += `</div>`;
                });

                html += '</div></div>';
                container.innerHTML = html;
            } catch (error) {
                container.innerHTML = `
                    <div class="automapping-result-card" style="background:#fff5f5; border-color:#fecaca;">
                        <h3 style="margin:0; color:#991b1b;">Consultas do AutoMapping (últimos 20 dias)</h3>
                        <p style="margin-top:8px; color:#7f1d1d; font-size:13px;">Não foi possível carregar o histórico.</p>
                    </div>
                `;
            }
        }

        async function getMappingResponse(cardId, clientId) {
            try {
                const response = await fetch(`${API_BASE}/environment/responses?client_id=${clientId}`);
                const responses = await response.json();
                return responses.find(r => r.card_id === cardId);
            } catch (error) {
                return null;
            }
        }

        async function openMappingCardModal(cardId) {
            // Se um cliente está selecionado, não abrir o modal (resposta já visível inline)
            if (mappingSelectedClient) return;

            // Abrir modal com todas as respostas
            try {
                const response = await fetch(`${API_BASE}/environment/card/${cardId}/all-responses`);
                const data = await response.json();

                const card = data.card;
                const responses = data.responses;

                let html = `<div class="modal active" id="mappingCardModal" onclick="if(event.target === this) closeMappingCardModal()">`;
                html += '<div class="modal-content" style="max-width: 800px;">';
                
                // Cabeçalho com botão de editar
                html += '<div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 20px;">';
                html += '<div style="flex: 1;">';
                html += `<input type="text" id="cardTitleEdit" value="${escapeHtml(card.title)}" style="width: 100%; font-size: 24px; font-weight: 700; color: #047857; border: 2px solid transparent; border-radius: 6px; padding: 4px 8px; margin-bottom: 10px;" onfocus="this.style.borderColor='#34D399'" onblur="this.style.borderColor='transparent'">`;
                html += `<textarea id="cardDescriptionEdit" style="width: 100%; color: #6b7280; border: 2px solid transparent; border-radius: 6px; padding: 4px 8px; resize: vertical; min-height: 50px;" onfocus="this.style.borderColor='#34D399'" onblur="this.style.borderColor='transparent'">${escapeHtml(card.description || '')}</textarea>`;
                html += '</div>';
                html += `<button class="btn btn-small btn-primary" onclick="saveCardEdit(${card.id})" style="margin-left: 10px;"><i class="fas fa-save"></i> Salvar Card</button>`;
                html += '</div>';

                if (responses.length === 0) {
                    html += '<div class="empty-state"><p>Nenhum cliente cadastrado</p></div>';
                } else {
                    // Ordenar: preenchidos primeiro (com fundo verde), depois alfabética
                    const sortedResponses = responses.sort((a, b) => {
                        const aFilled = (a.response || '').trim().length > 0;
                        const bFilled = (b.response || '').trim().length > 0;
                        
                        // Preenchidos primeiro
                        if (aFilled && !bFilled) return -1;
                        if (!aFilled && bFilled) return 1;
                        
                        // Dentro do mesmo grupo, ordem alfabética
                        return a.company.localeCompare(b.company, 'pt-BR');
                    });
                    
                    html += '<div style="max-height: 500px; overflow-y: auto;">';
                    sortedResponses.forEach((r, index) => {
                        const textareaId = `textarea-${card.id}-${r.id}`;
                        const counterId = `counter-${card.id}-${r.id}`;
                        const currentLength = (r.response || '').length;
                        const isFilled = currentLength > 0;
                        
                        // Fundo verde água (#D1FAE5) para preenchidos, branco para vazios
                        const bgColor = isFilled ? 'rgba(209, 250, 229, 0.6)' : 'rgba(255,255,255,0.9)';
                        
                        html += `<div style="border: 1px solid rgba(52, 211, 153, 0.2); border-radius: 10px; padding: 12px; margin-bottom: 10px; background: ${bgColor};">`;
                        html += `<div style="font-weight: 600; color: #047857; margin-bottom: 6px;">${escapeHtml(r.company)}</div>`;
                        html += '<div style="position: relative;">';
                        html += `<textarea id="${textareaId}" class="mapping-response-input" data-card-id="${card.id}" data-client-id="${r.id}" maxlength="1000" oninput="updateCharCounter('${textareaId}', '${counterId}')" style="width: 100%; min-height: 60px; padding: 8px; padding-bottom: 24px; border: 1px solid #e5e7eb; border-radius: 6px; resize: vertical;">${escapeHtml(r.response || '')}</textarea>`;
                        html += `<div id="${counterId}" style="position: absolute; bottom: 6px; right: 10px; font-size: 11px; color: #9ca3af;">${currentLength}/1000</div>`;
                        html += '</div>';
                        html += `<div style="text-align: right; margin-top: 6px;"><button class="btn btn-small btn-primary" onclick="saveMappingResponse(${card.id}, ${r.id})">Salvar</button></div>`;
                        html += '</div>';
                    });
                    html += '</div>';
                }

                html += '<div style="margin-top: 20px; text-align: right;"><button class="btn btn-secondary" onclick="closeMappingCardModal()">Fechar</button></div>';
                html += '</div></div>';

                document.body.insertAdjacentHTML('beforeend', html);
            } catch (error) {
                showError('Erro ao carregar detalhes do card');
            }
        }

        function updateCharCounter(textareaId, counterId) {
            const textarea = document.getElementById(textareaId);
            const counter = document.getElementById(counterId);
            if (textarea && counter) {
                counter.textContent = `${textarea.value.length}/1000`;
            }
        }

        function closeMappingCardModal() {
            const modal = document.getElementById('mappingCardModal');
            if (modal) modal.remove();
        }

        async function saveMappingResponse(cardId, clientId) {
            try {
                const textarea = document.querySelector(`textarea[data-card-id="${cardId}"][data-client-id="${clientId}"]`);
                const responseText = textarea.value.trim();

                const response = await fetch(`${API_BASE}/environment/responses`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        card_id: cardId,
                        client_id: clientId,
                        response: responseText
                    })
                });

                if (response.ok) {
                    showSuccess('Resposta salva com sucesso!');
                    
                    // Verificar se foi uma sugestão de mapear ambiente
                    if (window.currentSuggestion && window.currentSuggestion.type === 'map_environment') {
                        if (parseInt(cardId) === window.currentSuggestion.data.card_id && parseInt(clientId) === window.currentSuggestion.data.client_id) {
                            await markSuggestionComplete(window.currentSuggestion.id);
                            window.currentSuggestion = null;
                        }
                    }
                    
                    // Fechar modal atual
                    closeMappingCardModal();
                    // Recarregar mapeamento para atualizar os cards
                    await loadMapeamento();
                    // Reabrir o modal para mostrar a atualização (verde + ordenado)
                    await openMappingCardModal(cardId);
                } else {
                    const error = await response.json();
                    showError(error.error || 'Erro ao salvar resposta');
                }
            } catch (error) {
                showError('Erro ao salvar resposta');
            }
        }

        // ── Auto-preencher via Web ──────────────────────────────────────────────

        function openEnvAutoFillModal() {
            const filterSelect = document.getElementById('mappingClientFilter');
            const selectedAccountId = parseInt(filterSelect?.value || '', 10);
            if (!selectedAccountId) { showError('Selecione uma conta antes de usar o Auto-preencher.'); return; }

            if (!document.getElementById('env-autofill-bunny-style')) {
                const style = document.createElement('style');
                style.id = 'env-autofill-bunny-style';
                style.textContent = `
                    @keyframes eaf-hop { 0%,100%{transform:translateY(-50%) scaleY(1)} 50%{transform:translateY(-70%) scaleY(.85)} }
                    @keyframes eaf-paw { 0%,100%{opacity:.25} 50%{opacity:.7} }
                    .eaf-bunny { position:absolute; right:-14px; top:50%; transform:translateY(-50%); font-size:18px; line-height:1; animation:eaf-hop .5s ease-in-out infinite; pointer-events:none; }
                    .eaf-paw { display:inline-block; font-size:10px; animation:eaf-paw 1s ease-in-out infinite; }
                    .eaf-paw:nth-child(2){animation-delay:.2s} .eaf-paw:nth-child(3){animation-delay:.4s}
                `;
                document.head.appendChild(style);
            }

            const accountName = (mappingAccounts || []).find(a => Number(a.id) === selectedAccountId)?.name || '';
            const html = `
                <div class="modal active" id="envAutoFillModal" onclick="if(event.target===this) closeEnvAutoFillModal()">
                    <div class="modal-content" style="max-width:680px;">
                        <div class="modal-header">
                            <h2 class="modal-title"><span class="ai-star-icon">✦</span> Auto-preencher via Web</h2>
                            <button class="modal-close" onclick="closeEnvAutoFillModal()">&#215;</button>
                        </div>
                        <div id="eafFormArea">
                            <p style="margin:0 0 16px; color:#6b7280; font-size:13px;">
                                Pesquisa a web sobre <strong>${escapeHtml(accountName)}</strong> e sugere respostas para cada card de mapeamento. Você revisa antes de salvar.
                            </p>
                            <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:10px; padding:10px 14px; margin-bottom:16px; font-size:13px; color:#166534;">
                                <strong>Conta:</strong> ${escapeHtml(accountName)}
                            </div>
                            <div id="eafError" style="display:none; background:#fef2f2; border:1px solid #fca5a5; color:#b91c1c; border-radius:8px; padding:10px; margin-bottom:12px; font-size:13px;"></div>
                        </div>
                        <div id="eafProgressArea" style="display:none; padding:20px 4px 12px;">
                            <div style="font-size:13px; color:#6b7280; margin-bottom:12px; text-align:center;" id="eafProgressStep">Iniciando...</div>
                            <div style="position:relative; background:#d1fae5; border-radius:99px; height:12px; overflow:visible; margin:0 16px 6px;">
                                <div id="eafProgressBar" style="position:relative; height:100%; width:5%; background:linear-gradient(90deg,#059669,#10b981,#34d399); border-radius:99px; transition:width .6s ease;">
                                    <span class="eaf-bunny">🐇</span>
                                </div>
                            </div>
                            <div style="display:flex; justify-content:space-between; align-items:center; padding:0 16px;">
                                <div style="font-size:12px; color:#10b981;"><span class="eaf-paw">🐾</span><span class="eaf-paw">🐾</span><span class="eaf-paw">🐾</span></div>
                                <div style="font-size:11px; color:#6b7280;" id="eafProgressPct">5%</div>
                            </div>
                        </div>
                        <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:8px;">
                            <button id="eafCancelBtn" class="btn btn-secondary" onclick="closeEnvAutoFillModal()">Cancelar</button>
                            <button id="eafSubmitBtn" class="btn btn-auto-mapping btn-small" onclick="submitEnvAutoFill(${selectedAccountId})">
                                <span class="ai-star-icon">✦</span> Pesquisar e Sugerir
                            </button>
                        </div>
                    </div>
                </div>`;
            document.getElementById('envAutoFillModal')?.remove();
            document.body.insertAdjacentHTML('beforeend', html);
        }

        function closeEnvAutoFillModal() {
            document.getElementById('envAutoFillModal')?.remove();
        }

        function _eafSetProgress(pct, step) {
            const bar = document.getElementById('eafProgressBar');
            const stepEl = document.getElementById('eafProgressStep');
            const pctEl = document.getElementById('eafProgressPct');
            if (bar) bar.style.width = Math.max(5, pct) + '%';
            if (stepEl) stepEl.textContent = step || '';
            if (pctEl) pctEl.textContent = Math.round(pct) + '%';
        }

        function _eafSetError(msg) {
            const el = document.getElementById('eafError');
            if (!el) return;
            if (msg) { el.textContent = msg; el.style.display = ''; }
            else { el.style.display = 'none'; el.textContent = ''; }
        }

        async function submitEnvAutoFill(accountId) {
            const submitBtn = document.getElementById('eafSubmitBtn');
            const formArea = document.getElementById('eafFormArea');
            const progressArea = document.getElementById('eafProgressArea');
            _eafSetError('');
            if (submitBtn) submitBtn.disabled = true;

            try {
                const res = await fetch(`${API_BASE}/environment/auto-fill`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ account_id: accountId })
                });
                const payload = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(payload.error || 'Falha ao iniciar pesquisa');

                const taskId = payload.task_id;
                if (!taskId) throw new Error('Resposta inesperada do servidor.');

                if (formArea) formArea.style.display = 'none';
                if (progressArea) progressArea.style.display = '';
                _eafSetProgress(5, 'Iniciando pesquisa...');

                const poll = setInterval(async () => {
                    try {
                        const tr = await fetch(`${API_BASE}/tasks/${taskId}`);
                        const task = await tr.json();
                        if (task.progress) _eafSetProgress(task.progress, task.step || '');
                        if (task.status === 'done') {
                            clearInterval(poll);
                            closeEnvAutoFillModal();
                            openEnvAutoFillResultModal(task.result);
                        } else if (task.status === 'error') {
                            clearInterval(poll);
                            if (formArea) formArea.style.display = '';
                            if (progressArea) progressArea.style.display = 'none';
                            _eafSetError(task.error || 'Erro ao processar pesquisa.');
                            if (submitBtn) submitBtn.disabled = false;
                        }
                    } catch (e) {
                        clearInterval(poll);
                        _eafSetError('Erro ao verificar status da pesquisa.');
                        if (submitBtn) submitBtn.disabled = false;
                    }
                }, 900);
            } catch (err) {
                _eafSetError(err.message || 'Erro ao iniciar pesquisa.');
                if (submitBtn) submitBtn.disabled = false;
            }
        }

        function openEnvAutoFillResultModal(result) {
            const suggestions = result?.suggestions || [];
            const found = suggestions.filter(s => s.found);
            const notFound = suggestions.filter(s => !s.found);

            let html = `<div class="modal active" id="envAutoFillResultModal" onclick="if(event.target===this) closeEnvAutoFillResultModal()">`;
            html += '<div class="modal-content" style="max-width:860px;">';
            html += `<div class="modal-header"><h2 class="modal-title"><span class="ai-star-icon">✦</span> Sugestões de Preenchimento — ${escapeHtml(result?.company || '')}</h2><button class="modal-close" onclick="closeEnvAutoFillResultModal()">&#215;</button></div>`;

            if (!mappingSelectedClient) {
                html += '<div style="background:#fff7ed; border:1px solid #fdba74; color:#9a3412; border-radius:10px; padding:10px 14px; margin-bottom:14px; font-size:13px;"><strong>Atenção:</strong> Nenhum contato vinculado a esta conta. Vincule um contato para salvar as respostas.</div>';
            }

            html += `<p style="color:#6b7280; font-size:13px; margin-bottom:16px;">${found.length} de ${suggestions.length} cards com sugestão encontrada.</p>`;

            if (found.length > 0 && mappingSelectedClient) {
                html += `<div style="text-align:right; margin-bottom:12px;"><button class="btn btn-auto-mapping btn-small" onclick="applyAllEnvSuggestions()"><span class="ai-star-icon">✦</span> Aplicar todos (${found.length})</button></div>`;
            }

            html += '<div style="max-height:62vh; overflow-y:auto; padding-right:4px;">';

            suggestions.forEach((s, idx) => {
                const bgColor = s.found ? 'rgba(209,250,229,0.5)' : 'rgba(243,244,246,0.8)';
                const borderColor = s.found ? 'rgba(52,211,153,0.35)' : '#e5e7eb';
                html += `<div id="eafSuggCard_${idx}" style="border:1px solid ${borderColor}; border-radius:10px; padding:14px; margin-bottom:10px; background:${bgColor};">`;
                html += `<div style="font-weight:600; color:#047857; margin-bottom:8px;">${escapeHtml(s.card_title)}</div>`;

                if (s.found) {
                    const taId = `eafTa_${idx}`;
                    html += `<textarea id="${taId}" maxlength="1000" style="width:100%; min-height:70px; padding:8px; border:1px solid #d1d5db; border-radius:6px; resize:vertical; font-size:13px;">${escapeHtml(s.suggestion)}</textarea>`;
                    if (s.sources?.length) {
                        html += '<div style="margin-top:6px;">';
                        s.sources.slice(0, 2).forEach(src => {
                            html += `<div style="font-size:11px; color:#6b7280; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">🔗 <a href="${escapeHtml(src)}" target="_blank" rel="noopener" style="color:#6b7280;">${escapeHtml(src)}</a></div>`;
                        });
                        html += '</div>';
                    }
                    if (mappingSelectedClient) {
                        html += `<div style="text-align:right; margin-top:8px;">`;
                        html += `<button class="btn btn-small btn-primary" onclick="applyEnvSuggestion(${s.card_id}, '${taId}', ${idx})">Aplicar</button>`;
                        html += `</div>`;
                    }
                } else {
                    html += '<div style="font-size:13px; color:#9ca3af;">Não encontrado na web.</div>';
                }
                html += '</div>';
            });

            html += '</div>';
            html += '<div style="margin-top:16px; text-align:right;"><button class="btn btn-secondary" onclick="closeEnvAutoFillResultModal()">Fechar</button></div>';
            html += '</div></div>';

            document.getElementById('envAutoFillResultModal')?.remove();
            document.body.insertAdjacentHTML('beforeend', html);

            // Guarda sugestões para o "Aplicar todos"
            window._eafCurrentSuggestions = suggestions;
        }

        function closeEnvAutoFillResultModal() {
            document.getElementById('envAutoFillResultModal')?.remove();
        }

        async function applyEnvSuggestion(cardId, textareaId, suggIdx) {
            if (!mappingSelectedClient) { showError('Nenhum contato vinculado a esta conta.'); return; }
            const ta = document.getElementById(textareaId);
            const text = ta ? ta.value.trim() : '';
            if (!text) { showError('Sugestão está vazia.'); return; }
            try {
                const res = await fetch(`${API_BASE}/environment/responses`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ card_id: cardId, client_id: mappingSelectedClient, response: text })
                });
                if (!res.ok) { const e = await res.json(); throw new Error(e.error || 'Falha ao salvar'); }
                const card = document.getElementById(`eafSuggCard_${suggIdx}`);
                if (card) { card.style.opacity = '0.45'; card.style.pointerEvents = 'none'; }
                showSuccess('Sugestão aplicada!');
                await loadMapeamento();
            } catch (err) {
                showError(err.message || 'Erro ao aplicar sugestão.');
            }
        }

        async function applyAllEnvSuggestions() {
            if (!mappingSelectedClient) { showError('Nenhum contato vinculado a esta conta.'); return; }
            const suggestions = (window._eafCurrentSuggestions || []).filter(s => s.found);
            if (!suggestions.length) return;
            let saved = 0;
            for (let i = 0; i < suggestions.length; i++) {
                const s = suggestions[i];
                const taId = `eafTa_${(window._eafCurrentSuggestions || []).indexOf(s)}`;
                const ta = document.getElementById(taId);
                const text = (ta ? ta.value : s.suggestion || '').trim();
                if (!text) continue;
                try {
                    const res = await fetch(`${API_BASE}/environment/responses`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ card_id: s.card_id, client_id: mappingSelectedClient, response: text })
                    });
                    if (res.ok) saved++;
                } catch (_) {}
            }
            showSuccess(`${saved} sugestão(ões) aplicada(s)!`);
            closeEnvAutoFillResultModal();
            await loadMapeamento();
        }

        // ── fim Auto-preencher via Web ──────────────────────────────────────────

        async function saveCardEdit(cardId) {
            const titleInput = document.getElementById('cardTitleEdit');
            const descriptionInput = document.getElementById('cardDescriptionEdit');
            
            if (!titleInput || !descriptionInput) return;
            
            const newTitle = titleInput.value.trim();
            const newDescription = descriptionInput.value.trim();
            
            if (!newTitle) {
                showError('Título do card não pode estar vazio');
                return;
            }
            
            try {
                const response = await fetch(`${API_BASE}/environment/cards/${cardId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        title: newTitle,
                        description: newDescription
                    })
                });

                if (response.ok) {
                    showSuccess('Card atualizado com sucesso!');
                    closeMappingCardModal();
                    await loadMapeamento();
                } else {
                    const error = await response.json();
                    showError(error.error || 'Erro ao atualizar card');
                }
            } catch (error) {
                showError('Erro ao atualizar card');
            }
        }

        function openCreateCardModal() {
            const html = `
                <div class="modal active" id="createCardModal" onclick="if(event.target === this) closeCreateCardModal()">
                    <div class="modal-content" style="max-width: 500px;">
                        <div class="modal-header">
                            <h2>Novo Card</h2>
                            <button class="modal-close" onclick="closeCreateCardModal()">×</button>
                        </div>
                        <div class="form-group">
                            <label>Título *</label>
                            <input type="text" id="newCardTitle" required style="width: 100%; padding: 10px; border: 2px solid #e5e7eb; border-radius: 8px;">
                        </div>
                        <div class="form-group">
                            <label>Descrição</label>
                            <textarea id="newCardDescription" rows="4" style="width: 100%; padding: 10px; border: 2px solid #e5e7eb; border-radius: 8px;"></textarea>
                        </div>
                        <div style="text-align: right; margin-top: 20px;">
                            <button class="btn btn-secondary" onclick="closeCreateCardModal()" style="margin-right: 10px;">Cancelar</button>
                            <button class="btn btn-primary" onclick="createCard()">Criar Card</button>
                        </div>
                    </div>
                </div>
            `;
            document.body.insertAdjacentHTML('beforeend', html);
        }

        function closeCreateCardModal() {
            const modal = document.getElementById('createCardModal');
            if (modal) modal.remove();
        }

        async function createCard() {
            const titleInput = document.getElementById('newCardTitle');
            const descriptionInput = document.getElementById('newCardDescription');
            
            const title = titleInput.value.trim();
            const description = descriptionInput.value.trim();
            
            if (!title) {
                showError('Título do card é obrigatório');
                return;
            }
            
            try {
                const response = await fetch(`${API_BASE}/environment/cards`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title, description })
                });

                if (response.ok) {
                    showSuccess('Card criado com sucesso!');
                    closeCreateCardModal();
                    await loadMapeamento();
                } else {
                    const error = await response.json();
                    showError(error.error || 'Erro ao criar card');
                }
            } catch (error) {
                showError('Erro ao criar card');
            }
        }

        async function deleteMappingCard(cardId) {
            const card = mappingCards.find(c => c.id === cardId);
            if (!card) return;
            
            if (!await uiConfirm(`Tem certeza que deseja deletar o card "${card.title}"?\n\nAtenção: Todas as respostas associadas a este card serão perdidas!`)) {
                return;
            }
            
            try {
                const response = await fetch(`${API_BASE}/environment/cards/${cardId}`, {
                    method: 'DELETE'
                });

                if (response.ok) {
                    showSuccess('Card deletado com sucesso!');
                    await loadMapeamento();
                } else {
                    const error = await response.json();
                    showError(error.error || 'Erro ao deletar card');
                }
            } catch (error) {
                showError('Erro ao deletar card');
            }
        }

        async function editMappingCard(cardId) {
            const card = mappingCards.find(c => c.id === cardId);
            if (!card) return;

            const newTitle = await uiPrompt('Título do Card:', card.title, 'Editar card');
            if (newTitle === null) return;

            const newDescription = await uiPrompt('Descrição do Card:', card.description || '', 'Editar card');
            if (newDescription === null) return;

            try {
                const response = await fetch(`${API_BASE}/environment/cards/${cardId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        title: newTitle.trim(),
                        description: newDescription.trim()
                    })
                });

                if (response.ok) {
                    showSuccess('Card atualizado com sucesso!');
                    await loadMapeamento();
                } else {
                    const error = await response.json();
                    showError(error.error || 'Erro ao atualizar card');
                }
            } catch (error) {
                showError('Erro ao atualizar card');
            }
        }

        let agendaMapByDay = {};

        async function loadAgenda() {
            const { start, end } = monthRange(agendaCurrentMonth);
            const startDate = start.toISOString().slice(0,10);
            const endDate = end.toISOString().slice(0,10);

            try {
                const response = await fetch(`${API_BASE}/agenda?start_date=${startDate}&end_date=${endDate}`);
                const items = await response.json();

                agendaMapByDay = {};
                items.forEach(item => {
                    agendaMapByDay[item.due_date] = agendaMapByDay[item.due_date] || [];
                    agendaMapByDay[item.due_date].push(item);
                });

                const monthLabel = agendaCurrentMonth.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });
                let html = '<div class="calendar-wrap">';
                html += `<div class="calendar-header"><button class="btn btn-secondary btn-small" onclick="changeAgendaMonth(-1)">◀</button><h3 style="color:#047857; text-transform:capitalize;">${monthLabel}</h3><button class="btn btn-secondary btn-small" onclick="changeAgendaMonth(1)">▶</button></div>`;
                html += '<div class="calendar-grid">';

                ['Seg','Ter','Qua','Qui','Sex','Sáb','Dom'].forEach(d => html += `<div style="font-weight:700;color:#059669;text-align:center;">${d}</div>`);

                const firstWeekday = (start.getDay() + 6) % 7;
                for (let i=0;i<firstWeekday;i++) html += '<div></div>';

                for (let d=1; d<=end.getDate(); d++) {
                    const day = new Date(agendaCurrentMonth.getFullYear(), agendaCurrentMonth.getMonth(), d);
                    const key = day.toISOString().slice(0,10);
                    const count = (agendaMapByDay[key] || []).length;
                    const clickHandler = count ? `onclick="openDayActivitiesModal('${key}')" style="cursor: pointer;"` : '';
                    html += `<div class="calendar-cell ${count ? 'has-items' : ''}" ${clickHandler}><strong>${d}</strong>${count ? `<span class="calendar-dot"></span><div style="font-size:11px;color:#047857;margin-top:4px;">${count} compromisso(s)</div>` : ''}</div>`;
                }

                html += '</div>';
                html += '<div class="agenda-list">';
                if (!items.length) html += '<div class="empty-state" style="padding:20px 8px;"><p>Nenhum compromisso neste mês.</p></div>';
                items.forEach(item => {
                    html += `<div class=\"history-item\"><div class=\"history-meta\">${formatDateBr(item.due_date)}${item.due_time ? ' '+escapeHtml(item.due_time) : ''} • ${escapeHtml(item.client_name || '-')}${item.client_company?` (${escapeHtml(item.client_company)})`:''}</div><div>${escapeHtml(item.title || item.notes || '-')}</div></div>`;
                });
                html += '</div></div>';

                document.getElementById('agendaContent').innerHTML = html;
            } catch (error) {
                showError('Erro ao carregar agenda');
            }
        }

        function changeAgendaMonth(delta) {
            agendaCurrentMonth = new Date(agendaCurrentMonth.getFullYear(), agendaCurrentMonth.getMonth() + delta, 1);
            loadAgenda();
        }

        function openDayActivitiesModal(dateKey) {
            const activities = agendaMapByDay[dateKey] || [];
            if (activities.length === 0) return;

            const dateFormatted = new Date(dateKey + 'T00:00:00').toLocaleDateString('pt-BR', { 
                weekday: 'long', 
                year: 'numeric', 
                month: 'long', 
                day: 'numeric' 
            });

            let html = `<div class="modal active" id="dayActivitiesModal" onclick="if(event.target === this) closeDayActivitiesModal()">`;
            html += '<div class="modal-content" style="max-width: 300px;">';
            html += `<h2 style="color: #047857; margin-bottom: 10px; text-transform: capitalize;">Atividades de ${dateFormatted}</h2>`;
            html += `<p style="color: #6b7280; margin-bottom: 20px;">${activities.length} compromisso(s) programado(s)</p>`;

            html += '<div style="max-height: 400px; overflow-y: auto;">';
            activities.forEach(activity => {
                html += '<div class="history-item" style="margin-bottom: 12px; display: flex; align-items: start; gap: 12px;">';
                
                // Foto do cliente
                const photoSrc = activity.client_photo || '/logo-coelho.png';
                html += `<img src="${photoSrc}" alt="${escapeHtml(activity.client_name)}" style="width: 48px; height: 48px; border-radius: 50%; object-fit: cover; border: 2px solid #34D399;" onerror="this.src='/logo-coelho.png'">`;
                
                // Informações da atividade
                html += '<div style="flex: 1;">';
                html += `<div class="history-meta">${escapeHtml(activity.client_name)} (${escapeHtml(activity.client_company)})</div>`;
                html += `<div style="color: #6b7280; font-size: 13px; margin-top: 4px;">${escapeHtml(activity.title || activity.notes || '-')}</div>`;
                if ((activity.source_type || '') !== 'account_presence') { html += `<div style=\"margin-top: 8px;\"><button class=\"btn btn-danger btn-small\" onclick=\"deleteAgendaItem('${activity.id}')\"><i class=\"fas fa-trash\"></i> Excluir evento</button></div>`; }
                html += '</div>';
                html += '</div>';
            });
            html += '</div>';

            html += '<div style="margin-top: 20px; text-align: right;"><button class="btn btn-secondary" onclick="closeDayActivitiesModal()">Fechar</button></div>';
            html += '</div></div>';

            document.body.insertAdjacentHTML('beforeend', html);
        }

        function closeDayActivitiesModal() {
            const modal = document.getElementById('dayActivitiesModal');
            if (modal) modal.remove();
        }


        async function deleteAgendaItem(commitmentId) {
            if (String(commitmentId).startsWith('acc-')) { showError('Evento de renovação é gerado automaticamente pela presença.'); return; }
            if (!await uiConfirm('Deseja realmente excluir este evento da agenda?')) return;
            const response = await fetch(`${API_BASE}/agenda/${commitmentId}`, { method: 'DELETE' });
            if (!response.ok) {
                showError('Erro ao excluir evento da agenda');
                return;
            }
            showSuccess('Evento da agenda excluído!');
            closeDayActivitiesModal();
            await loadAgenda();
        }

        function normalizePhoneForWhatsapp(phone) {
            if (!phone) return '';
            let digits = String(phone).replace(/\D/g, '');
            if (!digits) return '';
            if (digits.startsWith('00')) digits = digits.slice(2);
            if (!digits.startsWith('55') && (digits.length === 10 || digits.length === 11)) {
                digits = `55${digits}`;
            }
            return digits;
        }

        let whatsappWindowRef = null;
        let emailWindowRef = null;
        let chamadoJuridicoWindowRef = null;

        function openOrReuseExternalTab(windowRef, url) {
            if (windowRef && !windowRef.closed) {
                windowRef.location.href = url;
                windowRef.focus();
                return windowRef;
            }
            const newWindow = window.open(url, '_blank');
            if (newWindow) newWindow.focus();
            return newWindow;
        }

        // Abre o WhatsApp Web sempre na mesma aba, identificada pelo nome fixo 'toca_whatsapp_web'.
        // Se a aba já estiver aberta (mesmo após recarregar a página), o browser a reutiliza
        // automaticamente em vez de criar uma nova.
        function openWhatsAppTab(url) {
            if (whatsappWindowRef && !whatsappWindowRef.closed) {
                try {
                    whatsappWindowRef.location.href = url;
                    whatsappWindowRef.focus();
                    return whatsappWindowRef;
                } catch (e) { /* cross-origin: deixa o browser resolver pelo nome */ }
            }
            const win = window.open(url, 'toca_whatsapp_web');
            if (win) win.focus();
            whatsappWindowRef = win;
            return win;
        }

        // Preferência de envio do WhatsApp: 'desktop' usa o protocolo whatsapp:// (app instalado,
        // sem reload do WhatsApp Web a cada mensagem); 'web' mantém o comportamento antigo.
        function getWhatsAppPreference() {
            try {
                const v = localStorage.getItem('whatsappOpenPreference');
                return v === 'web' ? 'web' : 'desktop';
            } catch (e) { return 'desktop'; }
        }

        function setWhatsAppPreference(pref) {
            try { localStorage.setItem('whatsappOpenPreference', pref === 'web' ? 'web' : 'desktop'); } catch (e) {}
        }

        // Tenta abrir no WhatsApp Desktop via protocolo whatsapp://. Se a aba não perder foco em
        // ~1500ms, assume que o app não está instalado/registrado e cai no fallback para o Web.
        function openWhatsAppDesktopWithFallback(phone, message) {
            const desktopUrl = `whatsapp://send?phone=${encodeURIComponent(phone)}&text=${encodeURIComponent(message)}`;
            const webUrl = `https://web.whatsapp.com/send?phone=${encodeURIComponent(phone)}&text=${encodeURIComponent(message)}`;

            let resolved = false;
            const cleanup = () => {
                window.removeEventListener('blur', onBlur);
                document.removeEventListener('visibilitychange', onVisibility);
            };
            const onBlur = () => { if (!resolved) { resolved = true; cleanup(); } };
            const onVisibility = () => { if (document.hidden && !resolved) { resolved = true; cleanup(); } };
            window.addEventListener('blur', onBlur);
            document.addEventListener('visibilitychange', onVisibility);

            window.location.href = desktopUrl;

            setTimeout(() => {
                if (!resolved) {
                    resolved = true;
                    cleanup();
                    whatsappWindowRef = openWhatsAppTab(webUrl);
                }
            }, 1500);
        }


        function openMissingContactModal() {
            let html = `<div class="modal active" id="missingContactModal" onclick="if(event.target === this) closeMissingContactModal()">`;
            html += '<div class="modal-content" style="max-width: 460px; text-align: center;">';
            html += '<h2 style="margin-bottom: 8px;">Ops!</h2>';
            // Mantemos SVG versionado para evitar problemas com arquivos binários personalizados
            html += '<p style="color: #4b5563; font-size: 16px; margin: 10px 0 18px;">Você não cadastrou esse tipo de contato ainda</p>';
            html += '<button class="btn btn-secondary" onclick="closeMissingContactModal()">Fechar</button>';
            html += '</div></div>';
            document.body.insertAdjacentHTML('beforeend', html);
        }

        function closeMissingContactModal() {
            const modal = document.getElementById('missingContactModal');
            if (modal) modal.remove();
        }

        function openWhatsAppMessageModal(clientId) {
            const client = clients.find(c => c.id === clientId);
            if (!client || !client.phone) {
                openMissingContactModal();
                return;
            }

            const prefDesktop = getWhatsAppPreference() === 'desktop';
            let html = `<div class="modal active" id="whatsAppModal">`;
            html += '<div class="modal-content" style="max-width: 520px;">';
            html += `<h2 style="margin-bottom: 8px; color: #047857;">Mensagem WhatsApp - ${escapeHtml(client.name)}</h2>`;
            html += '<p style="color:#6b7280; margin-bottom: 16px;">Digite a mensagem e nós abriremos o WhatsApp com o texto pronto para envio.</p>';
            html += '<div class="form-group"><label>Mensagem</label><textarea id="whatsMessageText" rows="5" placeholder="Digite a mensagem para o cliente..."></textarea></div>';
            html += `<label style="display:flex; align-items:center; gap:8px; font-size:13px; color:#4b5563; margin-bottom:12px;"><input type="checkbox" id="whatsUseDesktop" ${prefDesktop ? 'checked' : ''}> Abrir no WhatsApp Desktop (sem reload do Web)</label>`;
            html += `<div style="display:flex; gap:10px; justify-content:flex-end;"><button class="btn btn-secondary" onclick="closeWhatsAppModal()">Cancelar</button><button class="btn btn-primary" onclick="openWhatsAppWeb(${client.id})">Enviar mensagem</button></div>`;
            html += '</div></div>';
            document.body.insertAdjacentHTML('beforeend', html);
        }

        function closeWhatsAppModal() {
            const modal = document.getElementById('whatsAppModal');
            if (modal) modal.remove();
        }

        async function openWhatsAppWeb(clientId) {
            const client = clients.find(c => c.id === clientId);
            if (!client || !client.phone) {
                closeWhatsAppModal();
                openMissingContactModal();
                return;
            }

            const rawMessage = document.getElementById('whatsMessageText')?.value?.trim() || '';
            const message = applyMergeFields(rawMessage, client);
            const phone = normalizePhoneForWhatsapp(client.phone);

            if (!phone) {
                closeWhatsAppModal();
                openMissingContactModal();
                return;
            }

            const toggle = document.getElementById('whatsUseDesktop');
            if (toggle) setWhatsAppPreference(toggle.checked ? 'desktop' : 'web');

            if (getWhatsAppPreference() === 'desktop') {
                openWhatsAppDesktopWithFallback(phone, message);
            } else {
                const url = `https://web.whatsapp.com/send?phone=${encodeURIComponent(phone)}&text=${encodeURIComponent(message)}`;
                whatsappWindowRef = openWhatsAppTab(url);
            }
            closeWhatsAppModal();
            askRegisterActivityFromCommunication(clientId, 'WhatsApp', message);
        }

        function openEmailDraftModal(clientId) {
            const client = clients.find(c => c.id === clientId);
            if (!client || !client.email) {
                openMissingContactModal();
                return;
            }

            let html = `<div class="modal active" id="emailDraftModal">`;
            html += '<div class="modal-content" style="max-width: 520px;">';
            html += `<h2 style="margin-bottom: 8px; color: #047857;">Novo e-mail - ${escapeHtml(client.name)}</h2>`;
            html += '<p style="color:#6b7280; margin-bottom: 16px;">Digite o conteúdo do e-mail. Ao confirmar, será aberto um novo e-mail no Outlook/local para revisão antes do envio.</p>';
            html += '<div class="form-group"><label>Assunto</label><input id="emailDraftSubject" type="text" placeholder="Assunto do e-mail"></div>';
            html += '<div class="form-group"><label>Mensagem</label><textarea id="emailDraftBody" rows="6" placeholder="Escreva o corpo do e-mail..."></textarea></div>';
            html += `<div style="display:flex; gap:10px; justify-content:flex-end;"><button class="btn btn-secondary" onclick="closeEmailDraftModal()">Cancelar</button><button class="btn btn-primary" onclick="openOutlookDraft(${client.id})">Abrir no Outlook</button></div>`;
            html += '</div></div>';
            document.body.insertAdjacentHTML('beforeend', html);
        }

        function closeEmailDraftModal() {
            const modal = document.getElementById('emailDraftModal');
            if (modal) modal.remove();
        }

        function openOutlookDraft(clientId) {
            const client = clients.find(c => c.id === clientId);
            if (!client || !client.email) {
                closeEmailDraftModal();
                openMissingContactModal();
                return;
            }

            const subject = document.getElementById('emailDraftSubject')?.value?.trim() || '';
            const body = document.getElementById('emailDraftBody')?.value?.trim() || '';
            const outlookUrl = `https://outlook.office.com/mail/deeplink/compose?to=${encodeURIComponent(client.email)}&subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
            window.open(outlookUrl, '_blank');
            askRegisterActivityFromCommunication(clientId, 'Email', body);
            closeEmailDraftModal();
        }

        let autoMappingState = {
            result: null,
            runId: null,
            abortController: null,
            requestId: null
        };
        let autoMappingRunsHistory = [];

        function openAutoMappingModal() {
            const html = `
                <div class="modal active" id="autoMappingModal" onclick="if(event.target === this) closeAutoMappingModal()">
                    <div class="modal-content" style="max-width: 620px;">
                        <h2 style="color:#0f766e; margin-bottom: 10px;"><span class="ai-star-icon">✦</span>AutoMapping</h2>
                        <p style="color:#4b5563; margin-bottom: 16px; line-height: 1.5;">Bem vindo ao AutoMapping. Aqui nós faremos o possível para trazer informações do ambiente dos seus clientes. Por favor, digite abaixo o nome do cliente (empresa), a área de negócio e o país de origem do cliente.</p>
                        <div class="form-group">
                            <label>Cliente</label>
                            <input id="autoMappingClient" type="text" placeholder="Nome do cliente (empresa)" value="">
                        </div>
                        <div class="form-group">
                            <label>Área de Negócio</label>
                            <input id="autoMappingBusinessArea" type="text" placeholder="Área de negócio" value="">
                        </div>
                        <div class="form-group">
                            <label>País</label>
                            <input id="autoMappingCountry" type="text" placeholder="País de origem" value="">
                        </div>
                        <div id="autoMappingError" style="display:none; color:#b91c1c; font-size:13px; margin-top: 8px;"></div>
                        <div id="autoMappingProgressWrapper" style="display:none; margin-top:10px;">
                            <div id="autoMappingProgressText" style="font-size:13px; color:#374151;">Buscando evidências...</div>
                            <div class="automapping-progress"><div id="autoMappingProgressBar" class="automapping-progress-bar" style="width:0%;"></div></div>
                        </div>
                        <div style="display:flex; justify-content:flex-start; margin-top: 12px; gap:8px;">
                            <button class="btn btn-secondary" onclick="closeAutoMappingModal()">Cancelar</button>
                            <button id="autoMappingSubmitBtn" class="btn btn-primary" onclick="submitAutoMappingForm(false)">Enviar</button>
                        </div>
                    </div>
                </div>`;
            document.body.insertAdjacentHTML('beforeend', html);
        }

        async function closeAutoMappingModal() {
            if (autoMappingState.abortController && autoMappingState.requestId) {
                await cancelAutoMappingExecution();
            }
            const modal = document.getElementById('autoMappingModal');
            if (modal) modal.remove();
        }

        async function cancelAutoMappingExecution() {
            try {
                if (autoMappingState.abortController) {
                    autoMappingState.abortController.abort();
                }

                if (autoMappingState.requestId) {
                    await fetch(`${API_BASE}/automapping/cancel`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ request_id: autoMappingState.requestId })
                    });
                }
            } catch (error) {
                // Ignora erros no cancelamento para não bloquear fechamento do modal
            } finally {
                autoMappingState.abortController = null;
                autoMappingState.requestId = null;
            }
        }

        function normalizeAutoMappingKey(company, country, industry) {
            return [company, country, industry].map(v => (v || '').trim().toLowerCase()).join('|');
        }

        async function openExistingAutoMappingRun(runId) {
            try {
                const response = await fetch(`${API_BASE}/automapping/runs/${runId}`);
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || 'Falha ao carregar execução');
                autoMappingState.result = payload.result;
                autoMappingState.runId = payload.id;
                renderAutoMappingResultSection();
                openAutoMappingResultModal();
            } catch (error) {
                showError(`Não foi possível abrir o AutoMapping: ${error.message}`);
            }
        }

        function updateAutoMappingProgress(text, percent) {
            const wrapper = document.getElementById('autoMappingProgressWrapper');
            const label = document.getElementById('autoMappingProgressText');
            const bar = document.getElementById('autoMappingProgressBar');
            if (wrapper) wrapper.style.display = 'block';
            if (label) label.textContent = text;
            if (bar) bar.style.width = `${percent}%`;
        }

        function setAutoMappingError(message) {
            const el = document.getElementById('autoMappingError');
            if (!el) return;
            if (!message) {
                el.style.display = 'none';
                el.textContent = '';
                return;
            }
            el.style.display = 'block';
            el.textContent = message;
        }

        async function submitAutoMappingForm(forceRun = false) {
            const submitBtn = document.getElementById('autoMappingSubmitBtn');
            const clientName = document.getElementById('autoMappingClient')?.value?.trim();
            const businessArea = document.getElementById('autoMappingBusinessArea')?.value?.trim();
            const country = document.getElementById('autoMappingCountry')?.value?.trim();

            setAutoMappingError('');

            if (!clientName || !businessArea || !country) {
                setAutoMappingError('Preencha Cliente, Área de Negócio e País para continuar.');
                return;
            }

            const inputKey = normalizeAutoMappingKey(clientName, country, businessArea);
            const existingRun = (autoMappingRunsHistory || []).find(run => normalizeAutoMappingKey(run.company, run.country, run.industry) === inputKey);
            if (existingRun && !forceRun) {
                setAutoMappingError('Já existe um AutoMapping com as mesmas características (Cliente, Área de Negócio e País).');
                const shouldOpen = await openSystemDialog({
                    title: 'Consulta já existente',
                    message: 'Essa consulta já foi realizada. Deseja abrir o resultado existente?',
                    showCancel: true
                });
                if (shouldOpen) {
                    await openExistingAutoMappingRun(existingRun.id);
                    closeAutoMappingModal();
                }
                return;
            }

            if (submitBtn) submitBtn.disabled = true;

            try {
                autoMappingState.requestId = `am-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
                updateAutoMappingProgress('Iniciando AutoMapping...', 10);

                const response = await fetch(`${API_BASE}/automapping`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        company: clientName,
                        country,
                        industry: businessArea,
                        request_id: autoMappingState.requestId,
                        force: forceRun
                    })
                });

                const payload = await response.json().catch(() => ({}));
                if (!response.ok) {
                    if (payload.cancelled) { setAutoMappingError('AutoMapping cancelado pelo usuário.'); return; }
                    throw new Error(payload.error || 'Falha ao iniciar AutoMapping');
                }

                const taskId = payload.task_id;
                if (!taskId) throw new Error('Resposta inesperada do servidor.');

                updateAutoMappingProgress('Aguardando processamento...', 15);

                // Botões Cancelar / Minimizar no topo da barra de progresso
                const _amProgressEl = document.getElementById('autoMappingProgressWrapper');
                _attachBgTaskControls(
                    _amProgressEl, taskId,
                    () => closeAutoMappingModal(),
                    () => { closeAutoMappingModal(); if (submitBtn) submitBtn.disabled = false; }
                );

                const sourceTab = typeof _currentTab !== 'undefined' ? _currentTab : 'gestao-conta';
                BgTaskManager.register(
                    taskId,
                    `${API_BASE}/tasks/${taskId}`,
                    `AutoMapping — ${clientName}`,
                    sourceTab,
                    (result) => {
                        if (result && result.already_exists && !forceRun) {
                            setAutoMappingError('Já existe um AutoMapping para esses dados.');
                            autoMappingState.result = result.result;
                            autoMappingState.runId = result.run_id;
                        } else {
                            updateAutoMappingProgress('Concluído', 100);
                            autoMappingState.result = result.result || result;
                            autoMappingState.runId = result.run_id;
                        }
                        renderAutoMappingResultSection();
                        loadAutoMappingQueriesHistory();
                        openAutoMappingResultModal();
                        if (submitBtn) submitBtn.disabled = false;
                    },
                    (errMsg) => {
                        setAutoMappingError(errMsg || 'Falha no AutoMapping.');
                        if (submitBtn) submitBtn.disabled = false;
                    },
                    (pct, step) => updateAutoMappingProgress(step || 'Processando...', pct || 15)
                );
            } catch (error) {
                setAutoMappingError(`Não foi possível iniciar o AutoMapping: ${error.message}`);
                if (submitBtn) submitBtn.disabled = false;
            } finally {
                autoMappingState.abortController = null;
                autoMappingState.requestId = null;
            }
        }

        function renderAutoMappingResultSection() {
            const container = document.getElementById('autoMappingResultSection');
            if (!container) return;

            if (!autoMappingState.result) {
                container.innerHTML = '';
                return;
            }

            const result = autoMappingState.result;
            const sections = Object.keys(result.sections || {});
            container.innerHTML = `
                <div class="automapping-result-card">
                    <h3 style="margin:0 0 6px; color:#1d4ed8;">Resultado do AutoMapping</h3>
                    <p style="margin:0; color:#374151; font-size:13px;">Empresa: <strong>${escapeHtml(result.company)}</strong> · País: <strong>${escapeHtml(result.country)}</strong> · Área: <strong>${escapeHtml(result.industry)}</strong></p>
                    <p style="margin:8px 0 0; color:#6b7280; font-size:13px;">${sections.length} seções analisadas.</p>
                    <p style="margin:6px 0 0; color:#6b7280; font-size:12px;">Identificadas: <strong>${result.execution_summary?.identified_sections_count ?? 0}</strong> · Com erro: <strong>${result.execution_summary?.error_sections_count ?? 0}</strong></p>
                    <div style="margin-top:10px;"><button class="btn btn-primary" onclick="openAutoMappingResultModal()">Ver resultado completo</button></div>
                </div>
            `;
        }

        function getLLMSectionSummary(sectionKey) {
            const result = autoMappingState.result || {};
            const llmSummary = result.llm_summary || {};
            return llmSummary[sectionKey] || null;
        }

        function buildSectionSuggestionText(sectionKey, section) {
            const llm = getLLMSectionSummary(sectionKey);
            if (llm && llm.final_answer) {
                const pct = Number(llm.confidence_percent ?? 0);
                return `${llm.final_answer} (probabilidade: ${isNaN(pct) ? 0 : pct}%)`;
            }

            const confidence = section.confidence || 'unknown';
            if (section.status === 'error') return `Erro na coleta: ${section.error || 'Falha no provider'}`;
            if (section.value) return `${section.value} (confiança: ${confidence})`;
            if (Array.isArray(section.tools) && section.tools.length) return `${section.tools.join(', ')} (confiança: ${confidence})`;
            return `Status: ${section.status || 'unknown'} · Confiança: ${confidence}`;
        }

        function openAutoMappingResultModal() {
            if (!autoMappingState.result) {
                showError('Nenhum resultado disponível para exibição.');
                return;
            }
            const result = autoMappingState.result;
            const sectionEntries = Object.entries(result.sections || {});
            let html = `<div class="modal active" id="autoMappingResultModal" onclick="if(event.target === this) closeAutoMappingResultModal()">`;
            html += '<div class="modal-content" style="max-width: 900px;">';
            html += `<h2 style="color:#0f766e; margin-bottom:6px;">Resultado do AutoMapping</h2>`;
            html += `<p style="color:#4b5563; margin-bottom:10px;">${escapeHtml(result.company)} · ${escapeHtml(result.country)} · ${escapeHtml(result.industry)}</p>`;
            if (result.client_exists === false) {
                html += '<div style="background:#fff7ed; border:1px solid #fdba74; color:#9a3412; border-radius:10px; padding:10px; margin-bottom:10px; font-size:13px;"><strong>Aviso:</strong> não há registro desse cliente no sistema. Para registrar, cadastre o cliente pelo módulo GESTÃO DE CONTA.</div>';
            }
            html += '<div style="max-height:65vh; overflow:auto;">';

            sectionEntries.forEach(([key, section]) => {
                const llm = getLLMSectionSummary(key);
                const statusColor = section.status === 'identified' ? '#166534' : (section.status === 'error' ? '#b91c1c' : '#92400e');
                const suggestionText = buildSectionSuggestionText(key, section);
                html += `<div style="border:1px solid #e5e7eb; border-radius:10px; padding:12px; margin-bottom:10px;">`;
                html += `<div style="display:flex; justify-content:space-between; gap:10px; align-items:flex-start;">`;
                html += `<div><div style="font-weight:700; color:#111827; text-transform:capitalize;">${escapeHtml(key.replace('_', ' '))}</div><div style="font-size:11px; color:${statusColor}; margin-top:4px;">Status busca: ${escapeHtml(section.status || 'unknown')} · Confiança busca: ${escapeHtml(section.confidence || 'unknown')} · Quality: ${escapeHtml(String(section.evidence_quality ?? 0))}</div><div style="font-size:13px; color:#374151; margin-top:6px;">${escapeHtml(suggestionText)}</div>${llm ? `<div style="font-size:11px; color:#6b7280; margin-top:4px;">LLM: ${escapeHtml(llm.certainty || 'uncertain')} · ${escapeHtml(String(llm.confidence_percent ?? 0))}%</div>` : ''}<div style="font-size:11px; color:#6b7280; margin-top:4px;">Query: ${escapeHtml(section.query_used || 'n/a')}</div></div>`;
                html += `<button class="btn btn-primary btn-small" onclick="applyAutoMappingToCard('${escapeHtml(key)}')">Incluir no card referência</button>`;
                html += `</div>`;

                if (Array.isArray(section.evidence) && section.evidence.length) {
                    html += '<div style="margin-top:8px;">';
                    section.evidence.slice(0, 3).forEach(ev => {
                        html += `<div style="font-size:12px; color:#6b7280; margin-top:4px;">• <a href="${escapeHtml(ev.url || '#')}" target="_blank" rel="noopener">${escapeHtml(ev.url || 'Fonte')}</a> — ${escapeHtml(ev.snippet || '')}</div>`;
                    });
                    html += '</div>';
                }
                html += '</div>';
            });

            html += '</div>';
            html += '<div class="modal-footer" style="justify-content:flex-end;"><button class="btn btn-secondary" onclick="closeAutoMappingResultModal()">Fechar</button></div>';
            html += '</div></div>';

            const old = document.getElementById('autoMappingResultModal');
            if (old) old.remove();
            document.body.insertAdjacentHTML('beforeend', html);
        }

        async function closeAutoMappingResultModal() {
            const modal = document.getElementById('autoMappingResultModal');
            if (modal) modal.remove();

            // Se o modal de entrada ainda estiver aberto por trás, fechamos para voltar
            // ao estado inicial do módulo de Mapeamento de Ambiente.
            const formModal = document.getElementById('autoMappingModal');
            if (formModal) formModal.remove();

            autoMappingState.result = null;
            autoMappingState.runId = null;
            renderAutoMappingResultSection();

            if (_currentTab === 'gestao-conta' && _gestaoContaCurrentSubTab === 'environment') {
                await loadMapeamento();
            }
        }

        function closeAutoMappingCardPicker(result = null) {
            const modal = document.getElementById('autoMappingCardPickerModal');
            if (window._autoMappingCardPickerResolve) {
                window._autoMappingCardPickerResolve(result);
                window._autoMappingCardPickerResolve = null;
            }
            if (modal) modal.remove();
        }

        function openAutoMappingCardPicker(sectionKey) {
            return new Promise(resolve => {
                window._autoMappingCardPickerResolve = resolve;
                const options = (mappingCards || []).map(c => `<option value="${c.id}">${escapeHtml(c.title)}</option>`).join('');
                const html = `
                    <div class="modal active" id="autoMappingCardPickerModal" onclick="if(event.target===this) closeAutoMappingCardPicker(null)">
                        <div class="modal-content" style="max-width:520px;">
                            <h2 style="color:#0f766e; margin-bottom:8px;">Escolher card de destino</h2>
                            <p style="color:#4b5563; margin-bottom:10px; font-size:13px;">Não encontramos card compatível para <strong>${escapeHtml(sectionKey)}</strong>. Escolha em qual card deseja inserir a informação.</p>
                            <select id="autoMappingCardPickerSelect" style="width:100%; padding:10px; border:1px solid #d1d5db; border-radius:8px;">${options}</select>
                            <div class="modal-footer" style="justify-content:flex-end; margin-top:12px;">
                                <button class="btn btn-secondary" onclick="closeAutoMappingCardPicker(null)">Cancelar</button>
                                <button class="btn btn-primary" onclick="closeAutoMappingCardPicker(document.getElementById('autoMappingCardPickerSelect').value)">Confirmar</button>
                            </div>
                        </div>
                    </div>`;
                document.body.insertAdjacentHTML('beforeend', html);
            });
        }

        async function applyAutoMappingToCard(sectionKey) {
            const result = autoMappingState.result;
            if (!result || !result.sections || !result.sections[sectionKey]) return;

            const company = result.company;
            const section = result.sections[sectionKey];
            const text = buildSectionSuggestionText(sectionKey, section);

            try {
                const clientsResponse = await fetch(`${API_BASE}/clientes`);
                const clientsList = await clientsResponse.json();
                const targetClient = clientsList.find(c => (c.company || '').toLowerCase() === company.toLowerCase()) || (mappingSelectedClient ? clientsList.find(c => c.id === mappingSelectedClient) : null);

                if (!targetClient) {
                    showError('Cliente não cadastrado no sistema. Cadastre no módulo GESTÃO DE CONTA para incluir essa informação em cards.');
                    return;
                }

                const cardKeyHints = {
                    cloud: ['cloud', 'nuvem'],
                    erp: ['erp'],
                    crm: ['crm'],
                    observability: ['observability', 'observabilidade', 'cyber'],
                    security: ['security', 'segurança', 'cyber'],
                    data_analytics: ['analytics', 'dados', 'bi', 'data'],
                    ai: ['ai', 'ia', 'inteligência artificial']
                };
                const hints = cardKeyHints[sectionKey] || [sectionKey.toLowerCase()];
                let card = mappingCards.find(c => hints.some(h => (c.title || '').toLowerCase().includes(h)));

                if (!card) {
                    if (!mappingCards.length) {
                        showError('Nenhum card disponível para incluir informação.');
                        return;
                    }
                    const selectedId = await openAutoMappingCardPicker(sectionKey);
                    if (!selectedId) return;
                    card = mappingCards.find(c => String(c.id) === String(selectedId));
                }

                if (!card) {
                    showError('Card de destino não encontrado.');
                    return;
                }

                const existing = await getMappingResponse(card.id, targetClient.id);
                const composed = existing && existing.response ? `${existing.response}

[AutoMapping ${new Date().toLocaleDateString('pt-BR')}] ${text}` : `[AutoMapping ${new Date().toLocaleDateString('pt-BR')}] ${text}`;

                const saveResponse = await fetch(`${API_BASE}/environment/responses`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ card_id: card.id, client_id: targetClient.id, response: composed })
                });

                if (!saveResponse.ok) {
                    const err = await saveResponse.json();
                    throw new Error(err.error || 'Falha ao salvar no card');
                }

                showSuccess(`Sucesso! Informação incluída no card "${card.title}".`);
                await loadMapeamento();
            } catch (error) {
                showError(`Não foi possível incluir no card: ${error.message}`);
            }
        }

        async function markSuggestionComplete(suggestionId) {
            try {
                const response = await fetch(`${API_BASE}/suggestions/${suggestionId}/complete`, {
                    method: 'POST'
                });

                if (!response.ok) {
                    const error = await response.json();
                    showError(error.error || 'A sugestão ainda não foi concluída.');
                    return;
                }
                
            } catch (error) {
                console.error('Erro ao marcar sugestão como concluída:', error);
            }
        }

        // Get Status - Regra: < 7 dias = verde, 7-14 dias = amarelo, > 14 dias = vermelho
        // Sort function
        function sortClients(clientsArray, field, order) {
            const sorted = [...clientsArray].sort((a, b) => {
                const aArchived = isArchivedClient(a) ? 1 : 0;
                const bArchived = isArchivedClient(b) ? 1 : 0;
                if (aArchived !== bArchived) return aArchived - bArchived;

                if (field === 'status') {
                    const statusRank = { green: 1, yellow: 2, red: 3 };
                    const aStatusName = getStatus(a.last_activity_date, a.position, a.is_target, a.is_cold_contact);
                    const bStatusName = getStatus(b.last_activity_date, b.position, b.is_target, b.is_cold_contact);
                    const aStatus = statusRank[aStatusName] || 99;
                    const bStatus = statusRank[bStatusName] || 99;
                    if (aStatusName === bStatusName && Number(a.is_cold_contact) !== Number(b.is_cold_contact)) return Number(a.is_cold_contact) - Number(b.is_cold_contact);

                    if (aStatus < bStatus) return order === 'asc' ? -1 : 1;
                    if (aStatus > bStatus) return order === 'asc' ? 1 : -1;
                    return 0;
                }

                let aVal = a[field];
                let bVal = b[field];
                
                // Handle null/undefined
                if (aVal === null || aVal === undefined) aVal = '';
                if (bVal === null || bVal === undefined) bVal = '';
                
                // Convert to lowercase for string comparison
                if (typeof aVal === 'string') aVal = aVal.toLowerCase();
                if (typeof bVal === 'string') bVal = bVal.toLowerCase();
                
                if (aVal < bVal) return order === 'asc' ? -1 : 1;
                if (aVal > bVal) return order === 'asc' ? 1 : -1;
                return 0;
            });
            return sorted;
        }

        function toggleDashboardSort(field) {
            if (dashboardSortField === field) {
                dashboardSortOrder = dashboardSortOrder === 'asc' ? 'desc' : 'asc';
            } else {
                dashboardSortField = field;
                dashboardSortOrder = 'asc';
            }
            _renderDashboardTable();
        }

        function toggleDashboardArchivedSection() {
            dashboardArchivedExpanded = !dashboardArchivedExpanded;
            _renderDashboardTable();
        }

        function toggleClientsSort(field) {
            if (clientsSortField === field) {
                clientsSortOrder = clientsSortOrder === 'asc' ? 'desc' : 'asc';
            } else {
                clientsSortField = field;
                clientsSortOrder = 'asc';
            }
            loadClients();
        }

        function getStatus(lastActivityDate, position) {
            const cfgRule = (statusConfig.rules || []).find(rule => String(rule.position || '').toLowerCase() === String(position || '').toLowerCase());
            const greenDays = Number((cfgRule && cfgRule.green_days) || statusConfig.universal.green_days || 7);
            const yellowDays = Number((cfgRule && cfgRule.yellow_days) || statusConfig.universal.yellow_days || 14);

            if (!lastActivityDate) return 'red';
            const date = new Date(lastActivityDate);
            const days = Math.floor((new Date() - date) / (1000 * 60 * 60 * 24));
            if (days < greenDays) return 'green';
            if (days < yellowDays) return 'yellow';
            return 'red';
        }



        function escapeHtml(value) {
            return String(value || '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }

        function formatDateBr(dateValue) {
            if (!dateValue) return '-';
            return new Date(dateValue).toLocaleDateString('pt-BR');
        }

        function renderAvatar(client, className = 'mini-avatar') {
            if (client.photo_url) {
                return `<img src="${client.photo_url}" class="${className}">`;
            }
            const initial = (client.name || '?').charAt(0).toUpperCase();
            return `<div class="${className}">${initial}</div>`;
        }

        let _profileModalOpenClientId = null;

        async function openProfileModal(clientId) {
            try {
                const client = clients.find(c => c.id === clientId);
                if (!client) {
                    showError('Cliente não encontrado');
                    return;
                }
                _profileModalOpenClientId = clientId;

                const response = await fetch(`${API_BASE}/atividades`);
                const allActivities = await response.json();
                const clientActivities = allActivities
                    .filter(activity => Number(activity.client_id) === Number(clientId))
                    .sort((a, b) => new Date(b.activity_date || b.created_at) - new Date(a.activity_date || a.created_at));

                const status = getStatus(client.last_activity_date, client.position, client.is_target, client.is_cold_contact);
                const archivedContact = isArchivedClient(client);
                const statusText = archivedContact ? 'Arquivado' : (status === 'green' ? 'Em dia' : status === 'yellow' ? 'Atenção' : 'Atrasado');

                let historyHtml = '';
                if (clientActivities.length === 0) {
                    historyHtml = '<div class="empty-state" style="padding: 25px 10px;"><p>Nenhuma atividade registrada para este cliente.</p></div>';
                } else {
                    historyHtml = '<div class="history-list">';
                    clientActivities.forEach(activity => {
                        const dateRef = activity.activity_date || activity.created_at;
                        historyHtml += `
                            <div class="history-item">
                                <div class="history-meta">${formatDateBr(dateRef)} • ${escapeHtml(activity.contact_type || 'Outro')}</div>
                                <div>${escapeHtml(activity.information || activity.description || '-')}</div>
                            </div>
                        `;
                    });
                    historyHtml += '</div>';
                }

                const modalBody = `
                    <div style="display:flex; justify-content:flex-end; gap:8px; margin-bottom:10px; flex-wrap:wrap;">
                        <button class="btn btn-primary btn-small" onclick="openQuickActivityModal(${client.id}, '${escapeHtml(client.name)}', '${escapeHtml(client.company || '')}')"><i class="fas fa-plus-circle"></i> Registrar Atividade</button>
                        <button class="btn btn-edit-accent btn-small" onclick="openEditFromProfile(${client.id})"><i class="fas fa-edit"></i> Editar cliente</button>
                    </div>
                    <div class="profile-layout">
                        <div class="profile-avatar-wrap">${renderAvatar(client, 'profile-avatar-large')}${Number(client.is_cold_contact)===1?'<span class="snowflake-badge">❄</span>':''}</div>
                        <div>
                            <div class="profile-info-grid">
                                <div class="profile-field"><div class="profile-field-label">Nome</div><div class="profile-field-value">${escapeHtml(client.name)}</div></div>
                                <div class="profile-field"><div class="profile-field-label">Empresa</div><div class="profile-field-value">${escapeHtml(client.company || '-')}</div></div>
                                <div class="profile-field"><div class="profile-field-label">Cargo</div><div class="profile-field-value">${escapeHtml(client.position)}</div></div>
                                <div class="profile-field"><div class="profile-field-label">Status</div><div class="profile-field-value">${statusText}</div></div>
                                <div class="profile-field"><div class="profile-field-label">Email</div><div class="profile-field-value">${escapeHtml(client.email || '-')}</div></div>
                                <div class="profile-field"><div class="profile-field-label">Área de Atuação</div><div class="profile-field-value">${escapeHtml(client.area_of_activity || '-')}</div></div>
                                <div class="profile-field"><div class="profile-field-label">Contato Frio</div><div class="profile-field-value">${Number(client.is_cold_contact)===1?'Sim':'Não'}</div></div>
                                <div class="profile-field"><div class="profile-field-label">Telefone</div><div class="profile-field-value">${escapeHtml(client.phone || '-')}</div></div>
                                <div class="profile-field"><div class="profile-field-label">LinkedIn</div><div class="profile-field-value">${client.linkedin ? `<a href="${escapeHtml(client.linkedin)}" target="_blank" rel="noopener noreferrer" style="color:#0a66c2; text-decoration:none;">${escapeHtml(client.linkedin)}</a>` : '-'}</div></div>
                                <div class="profile-field"><div class="profile-field-label">Último contato</div><div class="profile-field-value">${formatDateBr(client.last_activity_date)}</div></div>
                                <div class="profile-field"><div class="profile-field-label">Cadastro</div><div class="profile-field-value">${formatDateBr(client.created_at)}</div></div>
                            </div>
                        </div>
                    </div>
                    <h3 class="history-title">Histórico de atividades</h3>
                    ${historyHtml}
                    <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:16px; flex-wrap:wrap;">
                        ${archivedContact ? `<button class="btn btn-small btn-archive-glass" onclick="unarchiveClient(${client.id}, { closeProfileOnSuccess: true })"><i class="fas fa-box-open"></i> Desarquivar Contato</button>` : `<button class="btn btn-small btn-archive-glass" onclick="archiveClient(${client.id}, { closeProfileOnSuccess: true })"><i class="fas fa-archive"></i> Arquivar Contato</button>`}
                        <button class="btn btn-danger btn-small" onclick="deleteClient(${client.id}, { closeProfileOnSuccess: true })"><i class="fas fa-trash"></i> Excluir contato</button>
                    </div>
                `;

                document.getElementById('profileModalBody').innerHTML = modalBody;
                document.getElementById('profileModal').classList.add('active');
            } catch (error) {
                showError('Erro ao abrir ficha do cliente');
            }
        }

        function closeProfileModal() {
            _profileModalOpenClientId = null;
            document.getElementById('profileModal').classList.remove('active');
        }

        async function openEditFromProfile(clientId) {
            closeProfileModal();
            await editClient(clientId);
        }

        function getCompanyImportanceRank(position) {
            const p = String(position || '').trim().toLowerCase();
            if (p === 'ceo') return 1;
            if (p === 'cio') return 2;
            if (p.startsWith('c') && p.length <= 5) return 3; // CHO, CISO, CMO, etc.
            if (p.includes('diretor') || p.includes('superintendente')) return 4;
            if (p.includes('gerente')) return 5;
            if (p.includes('coordenador')) return 6;
            return 7;
        }

        function sortGroupClients(groupType, list) {
            const arr = [...list];
            if (groupType === 'company') {
                arr.sort((a, b) => {
                    const rankDiff = getCompanyImportanceRank(a.position) - getCompanyImportanceRank(b.position);
                    if (rankDiff !== 0) return rankDiff;
                    return String(a.name || '').localeCompare(String(b.name || ''), 'pt-BR');
                });
                return arr;
            }
            arr.sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'pt-BR'));
            return arr;
        }

        async function exportCurrentGroupToXlsx() {
            if (!currentGroupModalContext) return;
            try {
                const params = new URLSearchParams({
                    group_type: currentGroupModalContext.groupType,
                    group_value: currentGroupModalContext.groupValue
                });
                const response = await fetch(`${API_BASE}/export/group-xlsx?${params.toString()}`);
                if (!response.ok) {
                    const payload = await response.json().catch(() => ({}));
                    showError(payload.error || 'Erro ao exportar grupo');
                    return;
                }
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `grupo-${currentGroupModalContext.groupType}-${currentGroupModalContext.groupValue}.xlsx`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);
            } catch (error) {
                showError('Erro ao exportar grupo');
            }
        }

        function openGroupModalFromEncoded(groupType, encodedValue) {
            const decodedValue = decodeURIComponent(encodedValue || '');
            openGroupModal(groupType, decodedValue);
        }

        function openGroupModal(groupType, groupValue) {
            const normalizedValue = String(groupValue || '').toLowerCase();
            let filtered = clients.filter(client => String(client[groupType] || '').toLowerCase() === normalizedValue);
            if (groupType === 'position') {
                const expanded = getGroupedPositions(groupValue).map(p => String(p || '').toLowerCase());
                filtered = clients.filter(client => expanded.includes(String(client.position || '').toLowerCase()));
            }
            const sortedGroup = sortGroupClients(groupType, filtered);

            const titlePrefix = groupType === 'position' ? 'Clientes com o cargo' : 'Clientes da empresa';
            document.getElementById('groupModalTitle').textContent = `${titlePrefix}: ${groupValue}`;

            let html = '';
            if (!sortedGroup.length) {
                html = '<div class="empty-state" style="padding: 25px 10px;"><p>Nenhum cliente encontrado.</p></div>';
            } else {
                html = '<div class="mini-card-grid">';
                sortedGroup.forEach(client => {
                    const subText = groupType === 'position' ? (client.company || '-') : (client.position || '-');
                    const groupHasExpansion = groupType === 'position' && getGroupedPositions(groupValue).length > 1;
                    const roleLine = groupHasExpansion ? `<div class="mini-card-sub" style="font-size:11px;">${escapeHtml(client.position || '-')}</div>` : '';
                    html += `
                        <div class="mini-card" style="cursor:pointer;" onclick="closeGroupModal(); openProfileModal(${client.id})">
                            ${renderAvatar(client)}
                            <div class="mini-card-name">${escapeHtml(client.name)}</div>
                            ${roleLine}
                            <div class="mini-card-sub">${escapeHtml(subText)}</div>
                        </div>
                    `;
                });
                html += '</div>';
                html += '<div style="display:flex; justify-content:flex-end; margin-top:12px;"><button class="btn btn-secondary btn-small" title="Exportar grupo" onclick="exportCurrentGroupToXlsx()"><i class="fas fa-file-export"></i></button></div>';
            }

            currentGroupModalContext = { groupType, groupValue };
            document.getElementById('groupModalBody').innerHTML = html;
            document.getElementById('groupModal').classList.add('active');
        }

        function closeGroupModal() {
            currentGroupModalContext = null;
            document.getElementById('groupModal').classList.remove('active');
        }

        // Show Success - usa toast azul quando o modulo Mapeamento Organizacional esta ativo
        function showSuccess(message) {
            // Show Success - usa toast azul quando o módulo Mapeamento Organizacional está ativo
            const orgActive = _currentTab === 'gestao-conta' && _gestaoContaCurrentSubTab === 'org';
            if (orgActive) {
                const el = document.getElementById('orgSuccessMsg');
                el.textContent = message;
                el.classList.add('show');
                setTimeout(() => el.classList.remove('show'), 3000);
            } else {
                const el = document.getElementById('successMsg');
                el.textContent = message;
                el.classList.add('show');
                setTimeout(() => el.classList.remove('show'), 3000);
            }
        }

        // Show Error
        function showError(message) {
            const el = document.getElementById('errorMsg');
            el.textContent = message;
            el.classList.add('show');
            setTimeout(() => el.classList.remove('show'), 3000);
        }

        // Show Info
        function showInfo(message) {
            // Mantém compatibilidade com fluxos que dependem de aviso não-bloqueante.
            // Reutiliza o toast de sucesso para evitar criar novo componente visual.
            showSuccess(message);
        }

        function closeSystemDialog(result = null) {
            const modal = document.getElementById('systemDialogModal');
            if (window._systemDialogResolve) {
                window._systemDialogResolve(result);
                window._systemDialogResolve = null;
            }
            if (modal) modal.remove();
        }

        function openSystemDialog({ title = 'Aviso', message = '', showCancel = false, inputDefault = null }) {
            return new Promise(resolve => {
                window._systemDialogResolve = resolve;
                const inputHtml = inputDefault !== null
                    ? `<input id="systemDialogInput" type="text" value="${escapeHtml(inputDefault)}" style="width:100%; margin-top:8px;">`
                    : '';
                const html = `
                    <div class="modal active" id="systemDialogModal" onclick="if(event.target===this) closeSystemDialog(${inputDefault !== null ? 'null' : 'false'})">
                        <div class="modal-content" style="max-width:520px; border:1px solid #fdba74; box-shadow:0 16px 34px rgba(249,115,22,0.22);">
                            <h2 style="color:#9a3412; margin-bottom:8px;">${escapeHtml(title)}</h2>
                            <p style="color:#7c2d12; line-height:1.5; white-space:pre-line;">${escapeHtml(message)}</p>
                            ${inputHtml}
                            <div class="modal-footer" style="justify-content:flex-end; margin-top:14px;">
                                ${showCancel ? '<button class="btn btn-secondary" style="background:#fed7aa; color:#7c2d12;" onclick="closeSystemDialog(false)">Cancelar</button>' : ''}
                                <button class="btn btn-primary" style="background:#fb923c;" onclick="closeSystemDialog(${inputDefault !== null ? "document.getElementById('systemDialogInput').value" : 'true'})">OK</button>
                            </div>
                        </div>
                    </div>`;
                const existing = document.getElementById('systemDialogModal');
                if (existing) existing.remove();
                document.body.insertAdjacentHTML('beforeend', html);
                if (inputDefault !== null) {
                    const input = document.getElementById('systemDialogInput');
                    if (input) { input.focus(); input.select(); }
                }
            });
        }

        async function uiConfirm(message, title = 'Confirmação') {
            return await openSystemDialog({ title, message, showCancel: true });
        }

        async function uiPrompt(message, defaultValue = '', title = 'Preenchimento') {
            return await openSystemDialog({ title, message, showCancel: true, inputDefault: defaultValue });
        }

        async function openArchiveContactDialog(client) {
            return await new Promise((resolve) => {
                const clientName = escapeHtml(client?.name || 'contato');
                const companyName = escapeHtml(client?.company || '-');
                const html = `
                    <div class="modal active" id="archiveContactDialog" onclick="if(event.target===this){ this.remove(); window.__archiveDialogResolve && window.__archiveDialogResolve({ confirmed:false, removeCompany:false }); window.__archiveDialogResolve = null; }">
                        <div class="modal-content" style="max-width:520px;">
                            <div class="modal-header">
                                <h2 style="color:#111827;">Arquivar Contato</h2>
                                <button class="modal-close" onclick="document.getElementById('archiveContactDialog')?.remove(); window.__archiveDialogResolve && window.__archiveDialogResolve({ confirmed:false, removeCompany:false }); window.__archiveDialogResolve = null;">×</button>
                            </div>
                            <div style="padding:8px 0 4px 0; color:#374151;">
                                <p style="margin-bottom:12px;">Deseja arquivar <strong>${clientName}</strong>?</p>
                                <label style="display:flex; align-items:flex-start; gap:10px; background:rgba(17,24,39,0.04); border:1px solid rgba(17,24,39,0.12); border-radius:10px; padding:10px;">
                                    <input type="checkbox" id="archiveRemoveCompanyCheck" style="margin-top:2px;">
                                    <span>Remover também o nome da empresa atual (<strong>${companyName}</strong>).</span>
                                </label>
                            </div>
                            <div class="modal-footer">
                                <button class="btn btn-secondary" onclick="document.getElementById('archiveContactDialog')?.remove(); window.__archiveDialogResolve && window.__archiveDialogResolve({ confirmed:false, removeCompany:false }); window.__archiveDialogResolve = null;">Cancelar</button>
                                <button class="btn btn-primary" onclick="const removeCompany = !!document.getElementById('archiveRemoveCompanyCheck')?.checked; document.getElementById('archiveContactDialog')?.remove(); window.__archiveDialogResolve && window.__archiveDialogResolve({ confirmed:true, removeCompany }); window.__archiveDialogResolve = null;">Arquivar</button>
                            </div>
                        </div>
                    </div>
                `;
                window.__archiveDialogResolve = resolve;
                document.body.insertAdjacentHTML('beforeend', html);
            });
        }

        async function openUnarchiveContactDialog(client) {
            const needsCompany = !String(client?.company || '').trim();
            let companyOptions = [];
            if (needsCompany) {
                try {
                    const res = await fetch(`${API_BASE}/empresas`);
                    companyOptions = res.ok ? await res.json() : [];
                } catch (e) { companyOptions = []; }
            }
            return await new Promise((resolve) => {
                const clientName = escapeHtml(client?.name || 'contato');
                const companySelectHtml = needsCompany
                    ? `<p style="margin-bottom:8px; color:#7c2d12;">Este contato não tem uma conta vinculada. Selecione a conta para a qual ele deve retornar:</p>
                       <select id="unarchiveCompanySelect" style="width:100%; margin-bottom:4px;">
                           <option value="">Selecione</option>
                           ${companyOptions.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('')}
                           <option value="__other__">Outros (digitar)</option>
                       </select>
                       <input type="text" id="unarchiveCompanyOther" placeholder="Digite a empresa" style="display:none; width:100%; margin-top:8px;">`
                    : `<p>Deseja desarquivar <strong>${clientName}</strong>? Ele voltará para a conta <strong>${escapeHtml(client?.company || '')}</strong>.</p>`;
                const html = `
                    <div class="modal active" id="unarchiveContactDialog" onclick="if(event.target===this){ this.remove(); window.__unarchiveDialogResolve && window.__unarchiveDialogResolve({ confirmed:false, company:'' }); window.__unarchiveDialogResolve = null; }">
                        <div class="modal-content" style="max-width:520px;">
                            <div class="modal-header">
                                <h2 style="color:#111827;">Desarquivar Contato</h2>
                                <button class="modal-close" onclick="document.getElementById('unarchiveContactDialog')?.remove(); window.__unarchiveDialogResolve && window.__unarchiveDialogResolve({ confirmed:false, company:'' }); window.__unarchiveDialogResolve = null;">×</button>
                            </div>
                            <div style="padding:8px 0 4px 0; color:#374151;">
                                ${needsCompany ? '<p style="margin-bottom:12px;">Desarquivar <strong>' + clientName + '</strong>.</p>' + companySelectHtml : companySelectHtml}
                            </div>
                            <div class="modal-footer">
                                <button class="btn btn-secondary" onclick="document.getElementById('unarchiveContactDialog')?.remove(); window.__unarchiveDialogResolve && window.__unarchiveDialogResolve({ confirmed:false, company:'' }); window.__unarchiveDialogResolve = null;">Cancelar</button>
                                <button class="btn btn-primary" onclick="(function(){
                                    var sel = document.getElementById('unarchiveCompanySelect');
                                    var other = document.getElementById('unarchiveCompanyOther');
                                    var company = sel ? (sel.value === '__other__' ? (other?.value || '').trim() : sel.value) : '';
                                    if (${needsCompany ? 'true' : 'false'} && !company) { showError('Selecione a conta de destino.'); return; }
                                    document.getElementById('unarchiveContactDialog')?.remove();
                                    window.__unarchiveDialogResolve && window.__unarchiveDialogResolve({ confirmed:true, company:company });
                                    window.__unarchiveDialogResolve = null;
                                })();">Desarquivar</button>
                            </div>
                        </div>
                    </div>
                `;
                window.__unarchiveDialogResolve = resolve;
                document.body.insertAdjacentHTML('beforeend', html);
                const sel = document.getElementById('unarchiveCompanySelect');
                if (sel) sel.addEventListener('change', () => {
                    const other = document.getElementById('unarchiveCompanyOther');
                    if (other) other.style.display = sel.value === '__other__' ? 'block' : 'none';
                });
            });
        }

        async function unarchiveClient(id, options = {}) {
            const client = clients.find(c => Number(c.id) === Number(id)) || {};
            const choice = await openUnarchiveContactDialog(client);
            if (!choice || !choice.confirmed) return;

            try {
                const response = await fetch(`${API_BASE}/clientes/${id}/desarquivar`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ company: choice.company || '' })
                });

                if (response.ok) {
                    if (options && options.closeProfileOnSuccess) {
                        closeProfileModal();
                    }
                    showSuccess('Contato desarquivado com sucesso!');
                    loadClients();
                    loadDashboard();
                } else {
                    const d = await response.json().catch(() => ({}));
                    showError(d.error || 'Erro ao desarquivar contato');
                }
            } catch (error) {
                showError('Erro ao desarquivar contato');
            }
        }


        function formatPhone(phone) {
            if (!phone) return '';
            const digits = String(phone).replace(/\D/g, '');
            if (digits.length < 10) return phone;
            const d = digits.length > 11 ? digits.slice(-11) : (digits.length === 10 ? `${digits.slice(0,2)}9${digits.slice(2)}` : digits);
            return `${d.slice(0,2)} ${d.slice(2,7)}.${d.slice(7,11)}`;
        }

        async function loadCompanyAndPositionOptions() {
            const [companiesRes, positionsRes] = await Promise.all([
                fetch(`${API_BASE}/empresas`),
                fetch(`${API_BASE}/cargos`)
            ]);
            const companies = companiesRes.ok ? await companiesRes.json() : [];
            const positions = positionsRes.ok ? await positionsRes.json() : [];
            const companySel = document.getElementById('clientCompanySelect');
            const positionSel = document.getElementById('clientPositionSelect');
            if (companySel) companySel.innerHTML = '<option value="">Selecione</option>' + companies.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('') + '<option value="__other__">Outros (digitar)</option>';
            if (positionSel) positionSel.innerHTML = '<option value="">Selecione</option>' + positions.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('') + '<option value="__other__">Outros (digitar)</option>';
        }

        function toggleOtherField(type) {
            const sel = document.getElementById(type === 'company' ? 'clientCompanySelect' : 'clientPositionSelect');
            const other = document.getElementById(type === 'company' ? 'clientCompanyOther' : 'clientPositionOther');
            if (!sel || !other) return;
            const isOther = sel.value === '__other__';
            other.style.display = isOther ? 'block' : 'none';
            other.required = isOther;
        }

        function getClientFieldValue(type) {
            const sel = document.getElementById(type === 'company' ? 'clientCompanySelect' : 'clientPositionSelect');
            const other = document.getElementById(type === 'company' ? 'clientCompanyOther' : 'clientPositionOther');
            return sel && sel.value === '__other__' ? (other?.value || '').trim() : (sel?.value || '').trim();
        }

        async function openClientModal() {
            currentEditingClientId = null;
            document.getElementById('clientModalTitle').textContent = 'Novo Cliente';
            document.getElementById('clientForm').reset();
            resetClientPhotoField();
            await loadCompanyAndPositionOptions();
            toggleOtherField('company');
            toggleOtherField('position');
            document.getElementById('clientModal').classList.add('active');
        }

        async function editClient(id) {
            const client = clients.find(c => c.id === id);
            if (!client) return;
            currentEditingClientId = id;
            document.getElementById('clientModalTitle').textContent = 'Editar Cliente';
            await loadCompanyAndPositionOptions();
            document.getElementById('clientForm').name.value = client.name;
            document.getElementById('clientForm').email.value = client.email || '';
            document.getElementById('clientForm').phone.value = formatPhone(client.phone || '');
            if (document.getElementById('clientForm').linkedin) document.getElementById('clientForm').linkedin.value = client.linkedin || '';
            document.getElementById('clientIsTarget').value = Number(client.is_target) === 1 ? '1' : '0';
            document.getElementById('clientColdContact').value = Number(client.is_cold_contact) === 1 ? '1' : '0';
            document.getElementById('clientForm').area_of_activity.value = client.area_of_activity || '';
            const cSel = document.getElementById('clientCompanySelect');
            const pSel = document.getElementById('clientPositionSelect');
            if ([...cSel.options].some(o => o.value === client.company)) cSel.value = client.company; else { cSel.value='__other__'; document.getElementById('clientCompanyOther').value = client.company || ''; }
            if ([...pSel.options].some(o => o.value === client.position)) pSel.value = client.position; else { pSel.value='__other__'; document.getElementById('clientPositionOther').value = client.position || ''; }
            toggleOtherField('company');
            toggleOtherField('position');
            resetClientPhotoField();
            if (client.photo_url) {
                const preview = document.getElementById('photoPreview');
                const removePhotoBtn = document.getElementById('removePhotoBtn');
                preview.src = client.photo_url; preview.style.display = 'block';
                if (removePhotoBtn) { removePhotoBtn.style.display='inline-flex'; removePhotoBtn.dataset.currentPhotoUrl = client.photo_url; }
            }
            document.getElementById('clientModal').classList.add('active');
        }

        async function saveClient(event) {
            event.preventDefault();
            const formData = new FormData(document.getElementById('clientForm'));
            const company = getClientFieldValue('company');
            const position = getClientFieldValue('position');
            formData.set('company', company);
            formData.set('position', position);
            formData.set('phone', formatPhone(formData.get('phone')));
            formData.set('linkedin', (formData.get('linkedin') || '').toString().trim());
            formData.set('is_target', document.getElementById('clientIsTarget').value === '1' ? '1' : '0');

            try {
                if (!currentEditingClientId) {
                    const duplicateRes = await fetch(`${API_BASE}/clients/check-duplicate`, {
                        method: 'POST', headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ name: formData.get('name'), email: formData.get('email'), phone: formData.get('phone') })
                    });
                    const duplicatePayload = await duplicateRes.json();
                    if (duplicatePayload.matches?.length) {
                        const possible = duplicatePayload.matches[0];
                        const shouldProceed = await openDuplicateWarningModal(possible);
                        if (!shouldProceed) return;
                        formData.set('force_create', '1');
                    }
                }
                const url = currentEditingClientId ? `${API_BASE}/clientes/${currentEditingClientId}` : `${API_BASE}/clientes`;
                const response = await fetch(url, { method: currentEditingClientId ? 'PUT' : 'POST', body: formData });
                if (!response.ok) throw new Error('Erro ao salvar cliente');
                showSuccess(currentEditingClientId ? 'Cliente atualizado!' : 'Cliente cadastrado!');
                const wasFromOrgMap = !!_orgMapOpenContext;
                closeClientModal(true);
                const reloadTasks = [loadClients(), loadDashboard(), loadPositions()];
                if (wasFromOrgMap) {
                    _orgMapOpenContext = null;
                    reloadTasks.push(loadOrganizationalMapping());
                }
                await Promise.all(reloadTasks);
            } catch (error) {
                showError('Erro ao salvar cliente: ' + error.message);
            }
        }

        async function toggleClientTarget(clientId, checked) {
            try {
                await fetch(`${API_BASE}/clients/${clientId}/target`, {
                    method: 'PUT', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ is_target: !!checked })
                });
                await Promise.all([loadClients(), loadDashboard()]);
            } catch (e) {
                showError('Erro ao atualizar target');
            }
        }

        async function openTargetAccountModal() {
            const companies = [...new Set(clients.map(c => c.company).filter(Boolean))].sort();
            const positions = [...new Set(clients.map(c => c.position).filter(Boolean))].sort();
            document.getElementById('targetCompanySelect').innerHTML = '<option value="">Selecione uma empresa</option>' + companies.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('');
            document.getElementById('targetPositionSelect').innerHTML = '<option value="">Selecione um cargo</option>' + positions.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('');
            document.getElementById('targetAccountModal').classList.add('active');
        }

        function closeTargetAccountModal() {
            document.getElementById('targetAccountModal').classList.remove('active');
        }

        async function applyTargetAccountBulk() {
            const company = document.getElementById('targetCompanySelect').value;
            const position = document.getElementById('targetPositionSelect').value;
            if (!company && !position) {
                showError('Selecione empresa ou cargo.');
                return;
            }
            const response = await fetch(`${API_BASE}/clients/target-bulk`, {
                method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ company, position })
            });
            if (response.ok) {
                closeTargetAccountModal();
                showSuccess('Target aplicado em massa!');
                await Promise.all([loadClients(), loadDashboard()]);
            } else showError('Erro ao aplicar target em massa');
        }


        async function saveColdStatus() {
            const green_days = Number(document.getElementById('coldGreen').value);
            const yellow_days = Number(document.getElementById('coldYellow').value);
            const response = await fetch(`${API_BASE}/config/status/cold`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ green_days, yellow_days })});
            if (response.ok) { showSuccess('Regra D por contato frio salva!'); await loadStatusConfig(); }
            else showError('Erro ao salvar regra D');
        }

        async function loadPositionGroupings() {
            const response = await fetch(`${API_BASE}/config/position-groupings`);
            if (response.ok) positionGroupings = await response.json();
            renderPositionGroupingList();
        }

        function renderPositionGroupingList() {
            const el = document.getElementById('positionGroupingList');
            if (!el) return;
            if (!positionGroupings.length) { el.innerHTML = '<div style="color:#6b7280;">Nenhum agrupamento cadastrado.</div>'; return; }
            el.innerHTML = positionGroupings.map(g => `<div class="rule-item"><div><strong>${escapeHtml(g.name)}</strong><div style="font-size:12px;color:#6b7280;">${escapeHtml((g.positions||[]).join(', '))}</div></div><button class="btn btn-danger btn-small" onclick="deletePositionGrouping(${g.id})"><i class="fas fa-trash"></i></button></div>`).join('');
        }

        async function savePositionGrouping() {
            const name = document.getElementById('groupingName').value.trim();
            const positions = document.getElementById('groupingPositions').value.split(',').map(v => v.trim()).filter(Boolean);
            if (!name || positions.length < 2) { showError('Informe um nome e ao menos 2 cargos.'); return; }
            const response = await fetch(`${API_BASE}/config/position-groupings`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ name, positions }) });
            const payload = await response.json();
            if (!response.ok) { showError(payload.error || 'Erro ao criar agrupamento'); return; }
            document.getElementById('groupingName').value=''; document.getElementById('groupingPositions').value='';
            await loadPositionGroupings();
            showSuccess('Agrupamento criado!');
        }

        async function deletePositionGrouping(id) {
            const response = await fetch(`${API_BASE}/config/position-groupings/${id}`, {method:'DELETE'});
            if (response.ok) { await loadPositionGroupings(); showSuccess('Agrupamento removido!'); }
        }

        function getGroupedPositions(position) {
            const normalized = String(position || '').toLowerCase();
            const group = positionGroupings.find(g => (g.positions || []).some(p => String(p).toLowerCase() === normalized));
            return group ? group.positions : [position];
        }

        async function askRegisterActivityFromCommunication(clientId, contactType, information) {
            const ok = await uiConfirm(`Deseja registrar essa interação de ${contactType} como atividade no cliente?`);
            if (!ok) return;
            const formData = new FormData();
            formData.set('client_id', clientId);
            formData.set('contact_type', contactType);
            formData.set('information', information || `${contactType} enviado.`);
            const response = await fetch(`${API_BASE}/atividades`, { method:'POST', body: formData });
            if (response.ok) { showSuccess('Atividade registrada com sucesso!'); await Promise.all([loadActivities(), loadDashboard()]); }
        }

