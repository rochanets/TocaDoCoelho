    (function(){
      const styleId = 'wa-sync-anim-style';
      if (!document.getElementById(styleId)) {
        const s = document.createElement('style');
        s.id = styleId;
        s.textContent = `
          @keyframes waPawFade  { 0%,100%{opacity:.25} 50%{opacity:.75} }
          .wa-paw { display:inline-block; animation:waPawFade 1s ease-in-out infinite; }
          .wa-switch { position:relative; display:inline-block; width:42px; height:24px; flex-shrink:0; vertical-align:middle; }
          .wa-switch input { opacity:0; width:0; height:0; }
          .wa-switch-slider { position:absolute; cursor:pointer; inset:0; background:#cbd5e1; border-radius:24px; transition:.25s; }
          .wa-switch-slider:before { content:""; position:absolute; height:18px; width:18px; left:3px; bottom:3px; background:#fff; border-radius:50%; transition:.25s; box-shadow:0 1px 2px rgba(0,0,0,.2); }
          .wa-switch input:checked + .wa-switch-slider { background:#059669; }
          .wa-switch input:checked + .wa-switch-slider:before { transform:translateX(18px); }
          .wa-switch.wa-switch-sm { width:34px; height:20px; }
          .wa-switch.wa-switch-sm .wa-switch-slider:before { height:14px; width:14px; }
          .wa-switch.wa-switch-sm input:checked + .wa-switch-slider:before { transform:translateX(14px); }
          .wa-state-label { font-size:12px; font-weight:600; min-width:54px; text-align:left; }
        `;
        document.head.appendChild(s);
      }
    })();

    let _waSelectedPeriod = 7;
    let _waQrPollInterval = null;
    let _waReviewItems = [];
    let _waLastDiagnosticsRunId = '';
    let _waLastDiagnosticText = '';

    function openWhatsappUpdateWithWarning() {
      setActiveAutoTocaModuleButton('autoTocaBtn_whatsapp-update');
      if (localStorage.getItem('wa_ban_warning_ok') === '1') {
        openWhatsappSyncModal();
        return;
      }
      const m = document.getElementById('waBanWarningModal');
      m.style.display = 'flex';
      document.getElementById('waBanWarningCheckbox').checked = false;
    }

    function closeWaBanWarning() {
      document.getElementById('waBanWarningModal').style.display = 'none';
      resetAutoTocaModuleButtons();
    }

    function confirmWaBanWarning() {
      if (document.getElementById('waBanWarningCheckbox').checked) {
        localStorage.setItem('wa_ban_warning_ok', '1');
      }
      closeWaBanWarning();
      openWhatsappSyncModal();
    }

    function openWhatsappSyncModal() {
      document.getElementById('whatsappSyncModal').style.display = 'block';
      _waShowSection('loading');
      _waCheckStatus();
    }

    function closeWhatsappSyncModal() {
      document.getElementById('whatsappSyncModal').style.display = 'none';
      if (_waQrPollInterval) { clearInterval(_waQrPollInterval); _waQrPollInterval = null; }
      if (typeof _waStatusRetryTimer !== 'undefined' && _waStatusRetryTimer) { clearTimeout(_waStatusRetryTimer); _waStatusRetryTimer = null; }
      resetAutoTocaModuleButtons();
    }

    function _waShowSection(name) {
      const sections = ['waSyncLoading','waSyncConfigArea','waSyncOfflineArea','waSyncQrArea','waSyncFormArea','waSyncProgressArea','waSyncResultArea'];
      sections.forEach(id => { const el = document.getElementById(id); if (el) el.style.display = 'none'; });
      const target = { loading:'waSyncLoading', config:'waSyncConfigArea', offline:'waSyncOfflineArea', qr:'waSyncQrArea', form:'waSyncFormArea', progress:'waSyncProgressArea', result:'waSyncResultArea' }[name];
      if (target) document.getElementById(target).style.display = '';
    }

    function _waShowConfig() {
      fetch('/api/whatsapp/config').then(r=>r.json()).then(d=>{
        document.getElementById('waConfigUrl').value = d.waha_api_url || 'http://localhost:3001';
        document.getElementById('waConfigKey').value = '';
        document.getElementById('waConfigInstance').value = d.waha_session_name || 'default';
        _waShowSection('config');
      }).catch(()=>_waShowSection('config'));
    }

    let _waStatusRetryTimer = null;

    function _waCheckStatus() {
      if (_waStatusRetryTimer) { clearTimeout(_waStatusRetryTimer); _waStatusRetryTimer = null; }
      fetch('/api/whatsapp/status').then(r=>r.json()).then(d=>{
        if (!d.configured) { _waShowConfig(); return; }
        if (d.state === 'starting') {
          document.getElementById('waSyncOfflineMsg').textContent = d.error || 'WAHA-lite está inicializando...';
          _waShowSection('offline');
          _waStatusRetryTimer = setTimeout(_waCheckStatus, 5000);
          return;
        }
        if (d.state === 'offline' || d.state === 'error' || d.state === 'unauthorized') {
          document.getElementById('waSyncOfflineMsg').textContent = d.error || 'WAHA não está acessível.';
          _waShowSection('offline');
          return;
        }
        if (d.connected) { _waShowConnectedForm(); return; }
        // not connected but configured → get QR
        _waGetQrCode();
      }).catch(()=>{ _waShowSection('offline'); document.getElementById('waSyncOfflineMsg').textContent = 'Não foi possível contatar o servidor.'; });
    }

    function _waSaveConfig() {
      const url = document.getElementById('waConfigUrl').value.trim();
      const key = document.getElementById('waConfigKey').value.trim();
      const inst = document.getElementById('waConfigInstance').value.trim();
      if (!url) { alert('A URL do WAHA é obrigatória.'); return; }
      fetch('/api/whatsapp/config', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({waha_api_url:url, waha_api_key:key, waha_session_name:inst||'default'})})
        .then(r=>r.json()).then(d=>{
          if (!d.ok) { alert('Erro ao salvar: ' + (d.error || 'Erro desconhecido.')); return; }
          _waShowSection('loading'); _waCheckStatus();
        })
        .catch(e=>alert('Erro ao salvar: '+e));
    }

    function _waGetQrCode() {
      fetch('/api/whatsapp/connect', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'})
        .then(r=>r.json()).then(d=>{
          if (!d.ok) { document.getElementById('waSyncOfflineMsg').textContent = d.error || 'Falha ao obter QR code.'; _waShowSection('offline'); return; }
          if (d.connected) { _waShowConnectedForm(); return; }
          if (d.qr) {
            document.getElementById('waSyncQrImg').src = d.qr;
            _waShowSection('qr');
            if (_waQrPollInterval) clearInterval(_waQrPollInterval);
            _waQrPollInterval = setInterval(()=>{
              fetch('/api/whatsapp/status').then(r=>r.json()).then(s=>{
                if (s.connected) { clearInterval(_waQrPollInterval); _waQrPollInterval = null; _waShowConnectedForm(); }
              });
            }, 3000);
          } else {
            document.getElementById('waSyncOfflineMsg').textContent = 'QR code não disponível. Verifique se a sessão WAHA foi iniciada.';
            _waShowSection('offline');
          }
        })
        .catch(e=>{ document.getElementById('waSyncOfflineMsg').textContent = 'Erro: '+e; _waShowSection('offline'); });
    }

    function selectWaPeriod(days) {
      _waSelectedPeriod = days;
      document.querySelectorAll('.wa-period-btn').forEach(b=>{
        const active = parseInt(b.dataset.days) === days;
        b.className = active ? 'btn btn-auto-mapping btn-small wa-period-btn wa-period-active' : 'btn btn-secondary btn-small wa-period-btn';
      });
    }

    function _waSetProgress(pct, step) {
      const safe = Math.max(5, pct);
      document.getElementById('waSyncProgressBar').style.width = safe + '%';
      document.getElementById('waSyncProgressStep').textContent = step;
      document.getElementById('waSyncProgressPct').textContent = Math.round(safe) + '%';
    }

    function startWhatsappSync() {
      _waShowSection('progress');
      _waSetProgress(5, 'Iniciando sincronização...');
      fetch('/api/whatsapp/sync', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({period_days:_waSelectedPeriod})})
        .then(r=>r.json()).then(d=>{
          if (!d.task_id) { alert('Erro ao iniciar sincronização.'); _waResetToForm(); return; }
          const taskId = d.task_id;
          _waLastDiagnosticsRunId = taskId.substring(0, 12);
          // Botões Minimizar / Cancelar — permite usar o sistema enquanto processa
          _attachBgTaskControls(
            document.getElementById('waSyncProgressArea'), taskId,
            () => { closeWhatsappSyncModal(); },   // minimizar: fecha o modal, a tarefa segue no background
            () => { _waResetToForm(); }             // cancelar: volta ao formulário
          );
          const sourceTab = (typeof _currentTab !== 'undefined') ? _currentTab : 'autotoca';
          BgTaskManager.register(
            taskId,
            '/api/whatsapp/tasks/' + taskId,
            'WhatsApp Update — analisando conversas',
            sourceTab,
            (result) => {            // onComplete — avisa quando termina
              const modal = document.getElementById('whatsappSyncModal');
              if (modal && modal.style.display === 'none') modal.style.display = 'block';
              _waShowResult(result);
            },
            (errMsg) => {            // onError
              const modal = document.getElementById('whatsappSyncModal');
              if (modal && modal.style.display === 'none') modal.style.display = 'block';
              _waShowResultError(errMsg);
            },
            (pct, step) => _waSetProgress(pct || 5, step || 'Processando...')   // progresso inline
          );
        })
        .catch(e=>{ alert('Erro: '+e); _waResetToForm(); });
    }

    function _waShowResult(result) {
      _waShowSection('result');
      const box = document.getElementById('waSyncResultBox');
      const reviewContainer = document.getElementById('waReviewContainer');
      const noItemsFooter = document.getElementById('waNoItemsFooter');
      const items = (result && result.items) || [];

      if (items.length > 0) {
        box.style.background = '#eff6ff';
        box.style.border = '1px solid #93c5fd';
        box.innerHTML = `<div style="font-weight:700; color:#1e40af; margin-bottom:4px;"><i class="fab fa-whatsapp" style="margin-right:6px;"></i>Análise concluída — revise os resumos</div><div style="color:#374151; font-size:13px;">${items.length} conversa(s) encontrada(s). Aceite ou rejeite cada uma antes de inserir no CRM.</div>`;

        _waReviewItems = items.map((item, idx) => Object.assign({}, item, {idx, state: 'accept', followup_enabled: !!item.followup_date}));

        const list = document.getElementById('waReviewList');
        list.innerHTML = '';
        _waReviewItems.forEach(function(item) {
          const card = document.createElement('div');
          card.id = 'waReviewCard_' + item.idx;
          card.style.cssText = 'border:1px solid #d1fae5; border-radius:8px; padding:12px 14px; background:#f0fdf4; transition:background .15s,border-color .15s;';
          const dateStr = item.activity_date ? item.activity_date.substring(0,10) : '';
          // Bloco de follow-up (FUP) — só aparece quando a IA detectou uma data combinada
          let fupHtml = '';
          if (item.followup_date) {
            const fd = item.followup_date.split('-');
            const fupBr = fd.length === 3 ? (fd[2] + '/' + fd[1] + '/' + fd[0]) : item.followup_date;
            fupHtml =
              '<div style="display:flex; align-items:center; gap:8px; margin-top:8px; padding:7px 10px; background:#eff6ff; border:1px solid #bfdbfe; border-radius:6px;">' +
                '<span style="font-size:12px; color:#1e40af; flex:1; min-width:0;">📅 <strong>Follow-up:</strong> ' + fupBr +
                  (item.followup_title ? ' — <span style="color:#374151;">' + item.followup_title + '</span>' : '') +
                  '<br><span style="font-size:10px; color:#6b7280;">Adicionar ao calendário do sistema</span>' +
                '</span>' +
                '<label class="wa-switch wa-switch-sm" title="Adicionar follow-up ao calendário">' +
                  '<input type="checkbox" id="waFupChk_' + item.idx + '" checked onchange="_waToggleFup(' + item.idx + ', this.checked)">' +
                  '<span class="wa-switch-slider"></span>' +
                '</label>' +
              '</div>';
          }
          card.innerHTML =
            '<div style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px;">' +
              '<strong style="font-size:13px; color:#111827; flex:1; min-width:0; word-break:break-word;">' + (item.client_name || '') + '</strong>' +
              '<div style="display:flex; align-items:center; gap:8px; flex-shrink:0;">' +
                '<span id="waStateLabel_' + item.idx + '" class="wa-state-label" style="color:#059669;">Incluir</span>' +
                '<label class="wa-switch" title="Incluir ou rejeitar esta conversa">' +
                  '<input type="checkbox" id="waSwitch_' + item.idx + '" checked onchange="_waToggleItem(' + item.idx + ', this.checked ? \'accept\' : \'reject\')">' +
                  '<span class="wa-switch-slider"></span>' +
                '</label>' +
              '</div>' +
            '</div>' +
            '<div style="font-size:13px; color:#374151; margin-top:8px; line-height:1.5;">' + (item.summary || '') + '</div>' +
            fupHtml +
            '<div style="font-size:11px; color:#9ca3af; margin-top:6px;">' + item.message_count + ' mensagem(ns)' + (dateStr ? ' · ' + dateStr : '') + '</div>';
          list.appendChild(card);
        });

        reviewContainer.style.display = '';
        noItemsFooter.style.display = 'none';
        _waUpdateReviewCounter();
      } else {
        const diagnostics = (result && result.diagnostics) || {};
        _waLastDiagnosticsRunId = diagnostics.run_id || '';
        const countLabels = {
          invalid_phone: 'Telefone inválido',
          unauthorized: 'API Key recusada',
          session_not_working: 'Sessão desconectada',
          chat_not_found: 'Conversa não localizada',
          waha_http_error: 'Erro HTTP do WAHA',
          waha_unavailable: 'WAHA indisponível',
          not_checked_after_timeout: 'Não verificado após timeout',
          invalid_response: 'Resposta inválida',
          no_messages_in_period: 'Sem mensagens no período',
          no_supported_content: 'Sem conteúdo importável',
          already_processed: 'Já importada'
        };
        const reasonLines = Object.entries(diagnostics.counts || {})
          .filter(function(entry){ return entry[1] > 0 && entry[0] !== 'ready_for_review'; })
          .map(function(entry){
            return '<li><strong>' + entry[1] + '</strong> — ' +
              escapeHtml(countLabels[entry[0]] || entry[0]) + '</li>';
          }).join('');
        const scope = diagnostics.scope || {};
        const scopeHtml = scope.total !== undefined
          ? '<div style="margin-top:7px; color:#64748b;">Escopo do banco: ' +
              '<strong>' + (scope.active_with_phone || 0) + '</strong> ativos com telefone de ' +
              (scope.total || 0) + ' contatos totais; ' +
              (scope.active_without_phone || 0) + ' ativos sem telefone; ' +
              (scope.archived_with_phone || 0) + ' arquivados com telefone.</div>'
          : '';
        const diagnosticHtml = diagnostics.summary
          ? '<div style="margin-top:12px; padding:10px 12px; background:#fffbeb; border:1px solid #fde68a; border-radius:8px; color:#78350f; font-size:12px;">' +
              '<strong>Diagnóstico:</strong> ' + escapeHtml(diagnostics.summary) +
              (reasonLines ? '<ul style="margin:7px 0 0 18px; padding:0;">' + reasonLines + '</ul>' : '') +
              scopeHtml +
            '</div>' +
            '<button type="button" class="btn btn-secondary btn-small" onclick="_waLoadDiagnostics()" style="margin-top:10px;">' +
              '<i class="fas fa-file-lines"></i> Ver log técnico do WAHA' +
            '</button>' +
            '<div id="waTechnicalDiagnostics" style="display:none; margin-top:10px;"></div>'
          : '';
        box.style.background = '#f9fafb';
        box.style.border = '1px solid #e5e7eb';
        box.innerHTML = `<div style="font-weight:700; color:#374151; margin-bottom:8px;"><i class="fas fa-check" style="margin-right:6px; color:#6b7280;"></i>Verificação concluída</div><div style="color:#6b7280;">${escapeHtml((result && result.message) || 'Nenhuma novidade encontrada no período.')}</div>${diagnosticHtml}`;
        reviewContainer.style.display = 'none';
        noItemsFooter.style.display = '';
      }
    }

    function _waShowConnectedForm() {
      _waShowSection('form');
      const scopeEl = document.getElementById('waSyncScopeInfo');
      if (!scopeEl) return;
      scopeEl.textContent = 'Calculando contatos que serão verificados...';
      fetch('/api/whatsapp/scope')
        .then(function(response){ return response.json(); })
        .then(function(data){
          if (!data.ok) throw new Error(data.error || 'Falha ao calcular escopo.');
          const scope = data.scope || {};
          scopeEl.innerHTML =
            '<strong>' + (scope.active_with_phone || 0) + ' contato(s) ativo(s) com telefone serão verificados.</strong> ' +
            (scope.active_without_phone || 0) + ' ativo(s) sem telefone e ' +
            (scope.archived_with_phone || 0) + ' arquivado(s) com telefone ficam fora da sincronização.';
        })
        .catch(function(){
          scopeEl.textContent = 'Não foi possível calcular previamente o escopo da sincronização.';
        });
    }

    async function _waLoadDiagnostics() {
      const panel = document.getElementById('waTechnicalDiagnostics');
      if (!panel) return;
      panel.style.display = '';
      panel.innerHTML = '<div style="color:#6b7280; font-size:12px;"><i class="fas fa-circle-notch fa-spin"></i> Carregando logs...</div>';
      try {
        const query = _waLastDiagnosticsRunId
          ? '?run_id=' + encodeURIComponent(_waLastDiagnosticsRunId) + '&limit=250'
          : '?limit=250';
        const response = await fetch('/api/whatsapp/diagnostics' + query);
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || 'Falha ao carregar diagnóstico.');

        const health = data.health || {};
        const sections = [
          'DIAGNÓSTICO WHATSAPP UPDATE',
          'Gerado em: ' + (data.generated_at || ''),
          'Execução: ' + (data.run_id || 'não informada'),
          'WAHA acessível: ' + (health.reachable ? 'sim' : 'não'),
          'Estado da sessão: ' + (health.session_state || health.gateway_state || 'desconhecido'),
          'Versão do gateway: ' + (health.gateway_version || (health.gateway_outdated ? 'antiga/incompatível' : 'não informada')),
          health.gateway_outdated ? 'ALERTA: o processo WAHA-lite ainda é antigo e precisa ser reiniciado.' : '',
          health.session_error ? 'Erro da sessão: ' + health.session_error : '',
          health.ping_error ? 'Erro de conexão: ' + health.ping_error : '',
          '',
          'LOG DO AUTOTOCA',
          ...(data.app_log || ['(sem linhas para esta execução)']),
          '',
          'LOG DO WAHA-LITE',
          ...(data.waha_log || ['(arquivo de log ainda não disponível)'])
        ].filter(function(line){ return line !== null && line !== undefined; });
        _waLastDiagnosticText = sections.join('\n');
        panel.innerHTML =
          '<div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:6px;">' +
            '<strong style="font-size:12px; color:#374151;">Log técnico (telefones e chaves ocultados)</strong>' +
            '<button type="button" class="btn btn-secondary btn-small" onclick="_waCopyDiagnostics()"><i class="fas fa-copy"></i> Copiar</button>' +
          '</div>' +
          '<pre style="max-height:280px; overflow:auto; margin:0; padding:10px; border-radius:7px; background:#111827; color:#d1fae5; white-space:pre-wrap; word-break:break-word; font-size:10.5px; line-height:1.45;">' +
            escapeHtml(_waLastDiagnosticText) +
          '</pre>';
      } catch (error) {
        panel.innerHTML = '<div style="color:#991b1b; font-size:12px;">Não foi possível carregar o log: ' +
          escapeHtml(error && error.message ? error.message : String(error)) + '</div>';
      }
    }

    async function _waCopyDiagnostics() {
      if (!_waLastDiagnosticText) return;
      try {
        await navigator.clipboard.writeText(_waLastDiagnosticText);
        showInfo('Diagnóstico do WhatsApp copiado.');
      } catch (_) {
        showInfo('Não foi possível copiar automaticamente. Selecione o texto do log.');
      }
    }

    function _waToggleItem(idx, action) {
      const item = _waReviewItems.find(function(i){ return i.idx === idx; });
      if (!item) return;
      item.state = action;
      const card = document.getElementById('waReviewCard_' + idx);
      const sw = document.getElementById('waSwitch_' + idx);
      const label = document.getElementById('waStateLabel_' + idx);
      if (sw) sw.checked = (action === 'accept');
      if (action === 'accept') {
        if (card) { card.style.borderColor = '#d1fae5'; card.style.background = '#f0fdf4'; card.style.opacity = '1'; }
        if (label) { label.textContent = 'Incluir'; label.style.color = '#059669'; }
      } else {
        if (card) { card.style.borderColor = '#e5e7eb'; card.style.background = '#f3f4f6'; card.style.opacity = '0.7'; }
        if (label) { label.textContent = 'Rejeitar'; label.style.color = '#9ca3af'; }
      }
      _waUpdateReviewCounter();
    }

    function _waToggleFup(idx, enabled) {
      const item = _waReviewItems.find(function(i){ return i.idx === idx; });
      if (item) item.followup_enabled = !!enabled;
    }

    function _waSelectAllItems(action) {
      _waReviewItems.forEach(function(item){ _waToggleItem(item.idx, action); });
    }

    function _waUpdateReviewCounter() {
      var accepted = _waReviewItems.filter(function(i){ return i.state === 'accept'; }).length;
      var rejected = _waReviewItems.filter(function(i){ return i.state === 'reject'; }).length;
      var counter = document.getElementById('waReviewCounter');
      if (counter) counter.innerHTML = '<span style="color:#059669; font-weight:600;">✓ ' + accepted + ' para incluir</span> &nbsp;·&nbsp; <span style="color:#9ca3af;">' + rejected + ' rejeitados</span>';
    }

    let _waLastInsertedItems = [];

    async function _waConfirmSelection() {
      var accepted = _waReviewItems.filter(function(i){ return i.state === 'accept'; });
      if (accepted.length === 0) {
        if (!await uiConfirm('Nenhuma conversa foi aceita. Deseja fechar sem inserir atividades?', 'Confirmar')) return;
        closeWhatsappSyncModal();
        return;
      }
      var btn = document.getElementById('waConfirmBtn');
      if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Inserindo...'; }
      fetch('/api/whatsapp/approve', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({items:accepted})})
        .then(function(r){ return r.json(); })
        .then(function(d){
          if (d.ok) {
            _waLastInsertedItems = accepted;
            _waShowFinalResult(d.inserted, _waReviewItems.length, d.commitments || 0);
          } else {
            alert('Erro ao inserir atividades: ' + (d.error || 'Erro desconhecido'));
            if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-check"></i> Confirmar e inserir aceitos'; }
          }
        })
        .catch(function(e){
          alert('Erro: ' + e);
          if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-check"></i> Confirmar e inserir aceitos'; }
        });
    }

    function _waShowFinalResult(inserted, total, commitments) {
      _waShowSection('result');
      const box = document.getElementById('waSyncResultBox');
      const reviewContainer = document.getElementById('waReviewContainer');
      const noItemsFooter = document.getElementById('waNoItemsFooter');
      box.style.background = '#ecfdf5';
      box.style.border = '1px solid #6ee7b7';
      var fupLine = (commitments && commitments > 0)
        ? '<div style="color:#1e40af; margin-top:6px; font-size:13px;">📅 ' + commitments + ' follow-up(s) adicionado(s) ao calendário do sistema.</div>'
        : '';
      box.innerHTML = '<div style="font-weight:700; color:#065f46; margin-bottom:8px;"><i class="fas fa-check-circle" style="margin-right:6px;"></i>Atividades inseridas!</div><div style="color:#374151;"><a href="javascript:void(0)" onclick="_waShowDetailsModal()" style="color:#065f46; font-weight:600; text-decoration:underline;">' + inserted + ' atividade(s) inserida(s) no CRM com sucesso.</a></div>' + fupLine;
      reviewContainer.style.display = 'none';
      noItemsFooter.style.display = '';
    }

    function _waShowDetailsModal() {
      const items = _waLastInsertedItems || [];
      const rows = items.map(function(item) {
        const fup = (item.followup_enabled && item.followup_date)
          ? '<div style="margin-top:4px; font-size:12px; color:#1e40af;">📅 Compromisso: ' + escapeHtml(item.followup_title || 'Follow-up') + ' — ' + escapeHtml(item.followup_date) + '</div>'
          : '<div style="margin-top:4px; font-size:12px; color:#9ca3af;">Sem compromisso criado</div>';
        return '<div style="border:1px solid #e5e7eb; border-radius:8px; padding:10px 12px; margin-bottom:8px;">'
          + '<div style="font-weight:600; color:#111827;">' + escapeHtml(item.client_name || 'Contato') + '</div>'
          + '<div style="font-size:12px; color:#6b7280; margin-top:2px;">Atividade registrada em ' + escapeHtml(item.activity_date || '') + '</div>'
          + '<div style="font-size:13px; color:#374151; margin-top:6px; white-space:pre-wrap;">' + escapeHtml(item.summary || '') + '</div>'
          + fup
          + '</div>';
      }).join('') || '<div style="color:#9ca3af;">Nenhum detalhe disponível.</div>';

      const modalHtml = `
        <div class="modal active" id="waDetailsModal" onclick="if(event.target===this) document.getElementById('waDetailsModal')?.remove();">
          <div class="modal-content" style="max-width:620px;">
            <div class="modal-header">
              <h2 style="color:#111827;">Detalhes da Sincronização WhatsApp</h2>
              <button class="modal-close" onclick="document.getElementById('waDetailsModal')?.remove();">×</button>
            </div>
            <div style="max-height:60vh; overflow-y:auto; padding:4px 2px;">${rows}</div>
            <div class="modal-footer" style="justify-content:flex-end; margin-top:14px;">
              <button class="btn btn-secondary" onclick="document.getElementById('waDetailsModal')?.remove();">Fechar</button>
            </div>
          </div>
        </div>`;
      const existing = document.getElementById('waDetailsModal');
      if (existing) existing.remove();
      document.body.insertAdjacentHTML('beforeend', modalHtml);
    }

    function _waShowResultError(error) {
      _waShowSection('result');
      const box = document.getElementById('waSyncResultBox');
      const reviewContainer = document.getElementById('waReviewContainer');
      const noItemsFooter = document.getElementById('waNoItemsFooter');
      box.style.background = '#fef2f2';
      box.style.border = '1px solid #fca5a5';
      box.innerHTML = `<div style="font-weight:700; color:#991b1b; margin-bottom:8px;"><i class="fas fa-exclamation-triangle" style="margin-right:6px;"></i>Erro durante sincronização</div><div style="color:#374151; font-size:13px;">${escapeHtml(error || 'Erro desconhecido.')}</div><button type="button" class="btn btn-secondary btn-small" onclick="_waLoadDiagnostics()" style="margin-top:10px;"><i class="fas fa-file-lines"></i> Ver log técnico do WAHA</button><div id="waTechnicalDiagnostics" style="display:none; margin-top:10px;"></div>`;
      if (reviewContainer) reviewContainer.style.display = 'none';
      if (noItemsFooter) noItemsFooter.style.display = '';
    }

    function _waResetToForm() {
      _waReviewItems = [];
      _waShowSection('form');
    }
