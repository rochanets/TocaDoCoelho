(function () {
    'use strict';

    const nativeFetch = window.fetch.bind(window);
    const SHAREABLE_TYPES = new Set([
        'clients', 'accounts', 'campaigns', 'commitments', 'activities',
        'wiki_entries', 'wiki_documents', 'portfolio_offers', 'iata_records',
        'account_archives', 'account_planning_runs', 'message_templates'
    ]);
    const sessionState = {
        status: 'loading',
        authEnabled: null,
        user: null,
        redirecting: false,
        lastForbiddenAt: 0,
        lastForbiddenMessage: ''
    };
    let shareContext = null;
    let shareReturnFocus = null;
    let authResolve;

    const ready = new Promise(resolve => { authResolve = resolve; });

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function isSameOriginProtectedRequest(input) {
        try {
            const raw = typeof input === 'string' ? input : input?.url;
            const url = new URL(raw, window.location.href);
            if (url.origin !== window.location.origin) return false;
            if (url.pathname.startsWith('/api/auth/')) return false;
            return url.pathname.startsWith('/api/') || url.pathname.startsWith('/uploads/');
        } catch (_) {
            return false;
        }
    }

    async function responseMessage(response, fallback) {
        try {
            const payload = await response.clone().json();
            return payload.error || payload.message || fallback;
        } catch (_) {
            return fallback;
        }
    }

    async function responseErrorPayload(response) {
        try {
            return await response.clone().json();
        } catch (_) {
            return {};
        }
    }

    function storeResumeState() {
        try {
            if (typeof window._tocaCurrentTab === 'string') {
                sessionStorage.setItem('toca.resume.tab', window._tocaCurrentTab);
            }
        } catch (_) {}
    }

    function setGateView(kind, message) {
        const gate = document.getElementById('sessionGate');
        const loading = document.getElementById('sessionGateLoading');
        const login = document.getElementById('sessionGateLogin');
        const title = document.getElementById('sessionGateTitle');
        const text = document.getElementById('sessionGateMessage');
        if (!gate) return;
        gate.hidden = false;
        if (loading) loading.hidden = kind !== 'loading';
        if (login) login.hidden = kind === 'loading';
        if (title) {
            title.textContent = kind === 'expired'
                ? 'Sua sessão expirou'
                : 'Bem-vindo de volta!';
        }
        if (text) {
            text.textContent = message || (
                kind === 'expired'
                    ? 'Entre novamente para continuar de onde parou.'
                    : 'Use sua conta corporativa Microsoft para continuar.'
            );
        }
        document.documentElement.classList.add('session-pending');
    }

    function hideGate() {
        const gate = document.getElementById('sessionGate');
        if (gate) gate.hidden = true;
        document.documentElement.classList.remove('session-pending');
    }

    function roleLabel(role) {
        return role === 'admin' ? 'Administrador' : 'Membro';
    }

    function renderAuthenticatedUser() {
        const block = document.getElementById('sessionUserBlock');
        const greeting = document.getElementById('dashboardGreeting');
        if (!block) return;
        if (!sessionState.authEnabled || !sessionState.user) {
            block.hidden = true;
            if (greeting) greeting.hidden = false;
            return;
        }
        const user = sessionState.user;
        const name = user.nickname || user.full_name || user.email || 'Usuário';
        const initial = name.trim().charAt(0).toUpperCase() || 'U';
        const avatar = block.querySelector('[data-session-avatar]');
        const nameEl = block.querySelector('[data-session-name]');
        const roleEl = block.querySelector('[data-session-role]');
        if (nameEl) nameEl.textContent = name;
        if (roleEl) roleEl.textContent = roleLabel(user.role);
        if (avatar) {
            avatar.replaceChildren();
            if (user.photo_url) {
                const img = document.createElement('img');
                img.src = user.photo_url;
                img.alt = '';
                img.addEventListener('error', () => {
                    avatar.textContent = initial;
                }, { once: true });
                avatar.appendChild(img);
            } else {
                avatar.textContent = initial;
            }
        }
        block.hidden = false;
        if (greeting) greeting.hidden = true;
    }

    function applySessionUi() {
        const body = document.body;
        if (!body) return;
        body.classList.toggle('auth-online', !!sessionState.authEnabled);
        body.dataset.userRole = isAdmin() ? 'admin' : 'member';
        renderAuthenticatedUser();
    }

    function notifyForbidden(message) {
        const now = Date.now();
        if (
            message === sessionState.lastForbiddenMessage
            && now - sessionState.lastForbiddenAt < 1200
        ) return;
        sessionState.lastForbiddenMessage = message;
        sessionState.lastForbiddenAt = now;
        if (typeof window.showError === 'function') {
            window.showError(message);
            return;
        }
        const notice = document.getElementById('sessionNotice');
        if (!notice) return;
        notice.textContent = message;
        notice.hidden = false;
        window.setTimeout(() => { notice.hidden = true; }, 4500);
    }

    function handleUnauthorized(message) {
        if (!sessionState.authEnabled || sessionState.status === 'unauthenticated') return;
        storeResumeState();
        sessionState.status = 'unauthenticated';
        sessionState.user = null;
        applySessionUi();
        setGateView('expired', message || 'Entre novamente para continuar de onde parou.');
    }

    window.fetch = async function tocaFetch(input, init) {
        const response = await nativeFetch(input, init);
        if (!isSameOriginProtectedRequest(input)) return response;
        if (response.status === 401) {
            const payload = await responseErrorPayload(response);
            if (payload.error_type === 'auth_required') {
                handleUnauthorized(payload.error || 'Sua sessão expirou.');
            } else {
                notifyForbidden(payload.error || 'A operação não pôde ser autenticada.');
            }
        } else if (response.status === 403) {
            notifyForbidden(await responseMessage(
                response,
                'Você não tem permissão para realizar esta ação.'
            ));
        }
        return response;
    };

    async function resolveSession() {
        setGateView('loading');
        try {
            const response = await nativeFetch('/api/auth/me', {
                credentials: 'same-origin',
                cache: 'no-store',
                headers: { Accept: 'application/json' }
            });
            if (!response.ok) throw new Error('Não foi possível verificar a sessão.');
            const payload = await response.json();
            sessionState.authEnabled = !!payload.auth_enabled;
            sessionState.user = payload.user || null;
            if (!sessionState.authEnabled) {
                sessionState.status = 'authenticated';
                applySessionUi();
                hideGate();
                authResolve(true);
                return;
            }
            if (payload.authenticated && payload.user) {
                sessionState.status = 'authenticated';
                applySessionUi();
                hideGate();
                authResolve(true);
                return;
            }
            sessionState.status = 'unauthenticated';
            applySessionUi();
            setGateView('login');
            authResolve(false);
        } catch (error) {
            sessionState.status = 'unauthenticated';
            sessionState.authEnabled = true;
            applySessionUi();
            setGateView(
                'login',
                error.message || 'Não foi possível verificar sua sessão. Tente novamente.'
            );
            authResolve(false);
        }
    }

    function login() {
        if (sessionState.redirecting) return;
        sessionState.redirecting = true;
        storeResumeState();
        window.location.assign('/api/auth/login?next=%2F');
    }

    async function logout() {
        const button = document.getElementById('sessionLogoutButton');
        if (button) button.disabled = true;
        try {
            await nativeFetch('/api/auth/logout', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { Accept: 'application/json' }
            });
        } finally {
            sessionState.status = 'unauthenticated';
            sessionState.user = null;
            applySessionUi();
            setGateView('login', 'Você saiu com segurança.');
            if (button) button.disabled = false;
        }
    }

    function isAdmin() {
        return !sessionState.authEnabled || sessionState.user?.role === 'admin';
    }

    function canManageShares(recordType, record) {
        if (!sessionState.authEnabled || sessionState.status !== 'authenticated') return false;
        if (!SHAREABLE_TYPES.has(recordType) || !record) return false;
        return isAdmin() || Number(record.owner_id) === Number(sessionState.user?.id);
    }

    function shareActionButton(recordType, record, label) {
        if (!canManageShares(recordType, record)) return '';
        const recordId = Number(record.id);
        if (!Number.isInteger(recordId) || recordId <= 0) return '';
        return `<button type="button" class="btn btn-secondary btn-small share-action-btn" ` +
            `data-share-label="${escapeHtml(label || '')}" ` +
            `onclick="event.stopPropagation(); openShareModal('${recordType}', ${recordId}, this.dataset.shareLabel)">` +
            '<i class="fas fa-user-plus"></i> Compartilhar</button>';
    }

    function modalFocusable(modal) {
        return Array.from(modal.querySelectorAll(
            'button:not([disabled]), select:not([disabled]), input:not([disabled]), ' +
            'textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'
        )).filter(el => !el.hidden && el.offsetParent !== null);
    }

    function shareKeydown(event) {
        const modal = document.getElementById('shareModal');
        if (!modal) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            closeShareModal();
            return;
        }
        if (event.key !== 'Tab') return;
        const focusable = modalFocusable(modal);
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    }

    function ensureShareModal() {
        let modal = document.getElementById('shareModal');
        if (modal) return modal;
        document.body.insertAdjacentHTML('beforeend', `
            <div id="shareModal" class="modal multiuser-modal" role="dialog"
                 aria-modal="true" aria-labelledby="shareModalTitle" hidden>
                <div class="modal-content multiuser-modal-content">
                    <div class="modal-header">
                        <div>
                            <p class="multiuser-eyebrow">Acesso ao registro</p>
                            <h2 id="shareModalTitle">Compartilhar</h2>
                            <p id="shareModalSubtitle" class="multiuser-subtitle"></p>
                        </div>
                        <button type="button" class="modal-close" onclick="closeShareModal()"
                                aria-label="Fechar compartilhamento">×</button>
                    </div>
                    <div id="shareModalStatus" class="multiuser-status" role="status"></div>
                    <form id="shareCreateForm" class="share-create-row"
                          onsubmit="createRecordShare(event)">
                        <div class="form-group">
                            <label for="shareRecipient">Pessoa</label>
                            <select id="shareRecipient" required></select>
                        </div>
                        <div class="form-group">
                            <label for="sharePermission">Permissão</label>
                            <select id="sharePermission">
                                <option value="read">Somente leitura</option>
                                <option value="write">Leitura e edição</option>
                            </select>
                        </div>
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-user-plus"></i> Adicionar
                        </button>
                    </form>
                    <div class="share-list-heading">
                        <h3>Acesso atual</h3>
                        <span id="shareCount"></span>
                    </div>
                    <div id="shareList" class="share-list"></div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary"
                                onclick="closeShareModal()">Fechar</button>
                    </div>
                </div>
            </div>`);
        modal = document.getElementById('shareModal');
        modal.addEventListener('click', event => {
            if (event.target === modal) closeShareModal();
        });
        modal.addEventListener('keydown', shareKeydown);
        return modal;
    }

    function setShareStatus(message, type) {
        const status = document.getElementById('shareModalStatus');
        if (!status) return;
        status.textContent = message || '';
        status.className = `multiuser-status${type ? ` is-${type}` : ''}`;
        status.hidden = !message;
    }

    function renderShareUsers(users) {
        const select = document.getElementById('shareRecipient');
        if (!select) return;
        if (!users.length) {
            select.innerHTML = '<option value="">Nenhum outro usuário disponível</option>';
            select.disabled = true;
            return;
        }
        select.disabled = false;
        select.innerHTML = '<option value="">Selecione uma pessoa</option>' + users.map(user => {
            const label = user.full_name || user.email || `Usuário ${user.id}`;
            const email = user.full_name && user.email ? ` — ${user.email}` : '';
            return `<option value="${Number(user.id)}">${escapeHtml(label + email)}</option>`;
        }).join('');
    }

    function renderShareList(shares) {
        const list = document.getElementById('shareList');
        const count = document.getElementById('shareCount');
        if (!list) return;
        if (count) count.textContent = shares.length ? `${shares.length} ativo(s)` : '';
        if (!shares.length) {
            list.innerHTML = `
                <div class="multiuser-empty">
                    <i class="fas fa-lock"></i>
                    <strong>Este registro ainda é privado</strong>
                    <span>Adicione uma pessoa para conceder acesso.</span>
                </div>`;
            return;
        }
        list.innerHTML = shares.map(share => {
            const name = share.shared_with_name || share.shared_with_email || 'Usuário';
            const email = share.shared_with_name && share.shared_with_email
                ? `<span>${escapeHtml(share.shared_with_email)}</span>` : '';
            return `
                <div class="share-list-item">
                    <div class="share-list-person">
                        <span class="share-list-avatar">${escapeHtml(name.charAt(0).toUpperCase())}</span>
                        <div><strong>${escapeHtml(name)}</strong>${email}</div>
                    </div>
                    <div class="share-list-actions">
                        <label class="sr-only" for="sharePermission-${share.id}">Permissão</label>
                        <select id="sharePermission-${share.id}"
                                onchange="updateRecordShare(${Number(share.id)}, this.value)">
                            <option value="read"${share.permission === 'read' ? ' selected' : ''}>Leitura</option>
                            <option value="write"${share.permission === 'write' ? ' selected' : ''}>Leitura e edição</option>
                        </select>
                        <button type="button" class="icon-btn-danger"
                                onclick="removeRecordShare(${Number(share.id)})"
                                aria-label="Remover acesso de ${escapeHtml(name)}">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>`;
        }).join('');
    }

    async function loadShareModalData() {
        if (!shareContext) return;
        setShareStatus('Carregando pessoas e acessos…', 'loading');
        const list = document.getElementById('shareList');
        if (list) list.innerHTML = '<div class="multiuser-loading"><span></span>Carregando</div>';
        try {
            const [usersResponse, sharesResponse] = await Promise.all([
                fetch('/api/shares/users'),
                fetch(`/api/shares/${encodeURIComponent(shareContext.recordType)}/${shareContext.recordId}`)
            ]);
            if (!usersResponse.ok || !sharesResponse.ok) {
                throw new Error('Não foi possível abrir o compartilhamento.');
            }
            const usersPayload = await usersResponse.json();
            const sharesPayload = await sharesResponse.json();
            renderShareUsers(usersPayload.users || []);
            renderShareList(sharesPayload.shares || []);
            setShareStatus('');
        } catch (error) {
            renderShareUsers([]);
            if (list) list.innerHTML = '';
            setShareStatus(error.message || 'Não foi possível carregar os acessos.', 'error');
        }
    }

    async function openShareModal(recordType, recordId, label) {
        if (!SHAREABLE_TYPES.has(recordType)) return;
        shareReturnFocus = document.activeElement;
        shareContext = { recordType, recordId: Number(recordId), label: label || '' };
        const modal = ensureShareModal();
        const subtitle = document.getElementById('shareModalSubtitle');
        if (subtitle) subtitle.textContent = label || 'Gerencie quem pode consultar ou editar.';
        modal.hidden = false;
        modal.classList.add('active');
        await loadShareModalData();
        const close = modal.querySelector('.modal-close');
        if (close) close.focus();
    }

    function closeShareModal() {
        const modal = document.getElementById('shareModal');
        if (modal) {
            modal.classList.remove('active');
            modal.hidden = true;
        }
        shareContext = null;
        if (shareReturnFocus?.focus) shareReturnFocus.focus();
        shareReturnFocus = null;
    }

    async function createRecordShare(event) {
        event.preventDefault();
        if (!shareContext) return;
        const recipient = Number(document.getElementById('shareRecipient')?.value);
        const permission = document.getElementById('sharePermission')?.value || 'read';
        if (!recipient) {
            setShareStatus('Selecione uma pessoa.', 'error');
            return;
        }
        setShareStatus('Salvando acesso…', 'loading');
        const response = await fetch('/api/shares', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                record_type: shareContext.recordType,
                record_id: shareContext.recordId,
                shared_with_user_id: recipient,
                permission
            })
        });
        if (!response.ok) {
            setShareStatus(await responseMessage(response, 'Não foi possível compartilhar.'), 'error');
            return;
        }
        await loadShareModalData();
        setShareStatus('Acesso salvo.', 'success');
    }

    async function updateRecordShare(shareId, permission) {
        setShareStatus('Atualizando permissão…', 'loading');
        const response = await fetch(`/api/shares/${shareId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ permission })
        });
        if (!response.ok) {
            setShareStatus(await responseMessage(response, 'Não foi possível atualizar.'), 'error');
            await loadShareModalData();
            return;
        }
        setShareStatus('Permissão atualizada.', 'success');
    }

    async function removeRecordShare(shareId) {
        if (typeof window.uiConfirm !== 'function') return;
        const confirmed = await window.uiConfirm(
            'Remover o acesso desta pessoa ao registro?',
            'Remover compartilhamento'
        );
        if (!confirmed) return;
        setShareStatus('Removendo acesso…', 'loading');
        const response = await fetch(`/api/shares/${shareId}`, { method: 'DELETE' });
        if (!response.ok) {
            setShareStatus(await responseMessage(response, 'Não foi possível remover.'), 'error');
            return;
        }
        await loadShareModalData();
        setShareStatus('Acesso removido.', 'success');
    }

    function adminStatus(message, type) {
        const el = document.getElementById('adminUsersStatus');
        if (!el) return;
        el.textContent = message || '';
        el.className = `multiuser-status${type ? ` is-${type}` : ''}`;
        el.hidden = !message;
    }

    function renderAdminUsers(users) {
        const list = document.getElementById('adminUsersList');
        if (!list) return;
        if (!users.length) {
            list.innerHTML = '<div class="multiuser-empty"><strong>Nenhum usuário provisionado</strong></div>';
            return;
        }
        list.innerHTML = users.map(user => {
            const name = user.full_name || user.email || `Usuário ${user.id}`;
            const isSelf = Number(user.id) === Number(sessionState.user?.id);
            return `
                <div class="admin-user-row">
                    <div class="admin-user-person">
                        <span class="share-list-avatar">${escapeHtml(name.charAt(0).toUpperCase())}</span>
                        <div>
                            <strong>${escapeHtml(name)}${isSelf ? ' <span class="self-badge">Você</span>' : ''}</strong>
                            <span>${escapeHtml(user.email || '')}</span>
                            <small>${user.linked ? 'Conta Microsoft vinculada' : 'Aguardando primeiro login'}</small>
                        </div>
                    </div>
                    <div class="admin-user-actions">
                        <label class="sr-only" for="adminRole-${user.id}">Papel de ${escapeHtml(name)}</label>
                        <select id="adminRole-${user.id}"
                                data-previous-role="${escapeHtml(user.role)}"
                                onchange="changeAdminUserRole(${Number(user.id)}, this)">
                            <option value="member"${user.role === 'member' ? ' selected' : ''}>Membro</option>
                            <option value="admin"${user.role === 'admin' ? ' selected' : ''}>Administrador</option>
                        </select>
                        <button type="button" class="icon-btn-danger"
                                onclick="deactivateAdminUser(${Number(user.id)}, ${isSelf})"
                                aria-label="Desativar ${escapeHtml(name)}">
                            <i class="fas fa-user-slash"></i>
                        </button>
                    </div>
                </div>`;
        }).join('');
    }

    async function loadAdminUsers() {
        if (!sessionState.authEnabled || !isAdmin()) return;
        const list = document.getElementById('adminUsersList');
        if (list) list.innerHTML = '<div class="multiuser-loading"><span></span>Carregando usuários</div>';
        adminStatus('');
        const response = await fetch('/api/admin/users');
        if (!response.ok) {
            adminStatus(await responseMessage(response, 'Não foi possível carregar os usuários.'), 'error');
            return;
        }
        const payload = await response.json();
        renderAdminUsers(payload.users || []);
    }

    async function createAdminUser(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const button = form.querySelector('button[type="submit"]');
        const payload = {
            full_name: form.elements.full_name.value.trim(),
            email: form.elements.email.value.trim(),
            role: form.elements.role.value
        };
        if (button) button.disabled = true;
        adminStatus('Provisionando usuário…', 'loading');
        try {
            const response = await fetch('/api/admin/users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!response.ok) {
                adminStatus(await responseMessage(response, 'Não foi possível provisionar.'), 'error');
                return;
            }
            form.reset();
            form.elements.role.value = 'member';
            await loadAdminUsers();
            adminStatus('Usuário provisionado. Ele já pode entrar com a conta Microsoft.', 'success');
        } finally {
            if (button) button.disabled = false;
        }
    }

    async function changeAdminUserRole(userId, select) {
        const previous = select.dataset.previousRole || 'member';
        const next = select.value;
        if (previous === next) return;
        const isSelf = Number(userId) === Number(sessionState.user?.id);
        let confirmed = true;
        if (isSelf && next === 'member') {
            confirmed = await window.uiConfirm(
                'Você perderá acesso às configurações administrativas. Deseja continuar?',
                'Rebaixar sua própria conta'
            );
        } else {
            confirmed = await window.uiConfirm(
                `Alterar o papel deste usuário para ${roleLabel(next)}?`,
                'Alterar papel'
            );
        }
        if (!confirmed) {
            select.value = previous;
            return;
        }
        select.disabled = true;
        const response = await fetch(`/api/admin/users/${userId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                role: next,
                confirm_self_change: isSelf && next === 'member'
            })
        });
        select.disabled = false;
        if (!response.ok) {
            select.value = previous;
            adminStatus(await responseMessage(response, 'Não foi possível alterar o papel.'), 'error');
            return;
        }
        select.dataset.previousRole = next;
        adminStatus('Papel atualizado.', 'success');
        if (isSelf) {
            sessionState.user.role = next;
            applySessionUi();
        }
        await loadAdminUsers();
    }

    async function deactivateAdminUser(userId, isSelf) {
        const message = isSelf
            ? 'Sua sessão será encerrada e você perderá o acesso. Seus dados serão preservados. Deseja continuar?'
            : 'O usuário perderá o acesso, mas seus dados e autoria serão preservados. Deseja continuar?';
        const confirmed = await window.uiConfirm(
            message,
            isSelf ? 'Desativar sua própria conta' : 'Desativar usuário'
        );
        if (!confirmed) return;
        adminStatus('Desativando usuário…', 'loading');
        const response = await fetch(`/api/admin/users/${userId}`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirm_self_change: !!isSelf })
        });
        if (!response.ok) {
            adminStatus(await responseMessage(response, 'Não foi possível desativar.'), 'error');
            return;
        }
        if (isSelf) {
            handleUnauthorized('Sua conta foi desativada.');
            return;
        }
        await loadAdminUsers();
        adminStatus('Usuário desativado sem apagar seus dados.', 'success');
    }

    function restoreResumeTab() {
        if (!sessionState.authEnabled || sessionState.status !== 'authenticated') return;
        let tab = '';
        try {
            tab = sessionStorage.getItem('toca.resume.tab') || '';
            sessionStorage.removeItem('toca.resume.tab');
        } catch (_) {}
        if (!tab || tab === 'dashboard') return;
        window.setTimeout(() => {
            if (typeof window.switchTab === 'function' && document.getElementById(tab)) {
                window.switchTab(null, tab);
            }
        }, 0);
    }

    window.TocaSession = {
        ready,
        state: sessionState,
        login,
        logout,
        isAdmin,
        canManageShares,
        shareActionButton,
        restoreResumeTab,
        notifyForbidden
    };
    window.openShareModal = openShareModal;
    window.closeShareModal = closeShareModal;
    window.createRecordShare = createRecordShare;
    window.updateRecordShare = updateRecordShare;
    window.removeRecordShare = removeRecordShare;
    window.loadAdminUsers = loadAdminUsers;
    window.createAdminUser = createAdminUser;
    window.changeAdminUserRole = changeAdminUserRole;
    window.deactivateAdminUser = deactivateAdminUser;

    resolveSession();
})();
