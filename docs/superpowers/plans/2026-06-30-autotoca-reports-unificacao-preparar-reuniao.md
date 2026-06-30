# Unificação AutoToca + Reports e Preparar Reunião enriquecido — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unificar os módulos Reports e AutoToca (mover subfunções de Reports para AutoToca, remover o menu Reports, mover AutoToca para abaixo de Dashboard) e enriquecer o "Preparar Reunião" com uma seção de Contexto da Conta (momento de mercado, relacionamento com o contato, Serviços Stefanini, fallback de foto).

**Architecture:** Frontend é SPA único em `public/index.html`; backend Flask em `app.py`. A unificação é puramente de marcação/JS no `index.html`. O enriquecimento adiciona helpers em `app.py` reaproveitando `_relation_report_fetch_market_context` (mercado), `account_presences` (Serviços Stefanini), `_iata_call_llm` (resumo de relacionamento via SAI→OpenRouter) e o fluxo assíncrono já existente de `/api/linkedin/summarize`.

**Tech Stack:** Python 3 + Flask + SQLite (`get_db()`); Vanilla JS/HTML.

**Sem framework de testes no projeto** (não há `tests/`, pytest, nem JS test runner). Verificação usa: `python -m py_compile app.py`, scripts Python de smoke isolados para os helpers novos, e verificação funcional rodando o app (`python app.py`, porta default 5000) e navegando na UI.

**Restrição do usuário:** manter o nome e o header/subtítulo do módulo **AutoToca** sem alteração.

---

## Arquivos afetados

- Modificar: `public/index.html`
  - Menu lateral (~3351): remover `nav-reports`, reposicionar `nav-autotoca`.
  - Aba `#autotoca` (~4085): adicionar botões e painéis de Reports.
  - Aba `#reports` (~3987): remover.
  - `switchTab` (~5411): remover wiring de `reports`, garantir `loadReports()` ao abrir `autotoca`.
  - `toggleReportsPanel` (~6443) / `toggleAutoTocaAutomation` (~6406): unificar fechamento de painéis.
  - Preparar Reunião JS (~17431+): enviar `account_id`, renderizar seção de Contexto da Conta.
- Modificar: `app.py`
  - Novos helpers próximos a `_linkedin_process_async` (~13076).
  - `_linkedin_process_async` e `linkedin_summarize()` (~13144): aceitar `account_id`, fallback de foto, retornar `account_context`.

---

## Task 1: Reordenar menu lateral e remover item Reports

**Files:**
- Modify: `public/index.html:3359-3386`

- [ ] **Step 1: Remover o botão `nav-reports` e mover `nav-autotoca` para abaixo de `nav-dashboard`**

Localizar o bloco atual (linhas ~3359-3386):

```html
            <button class="nav-item nav-dashboard" onclick="switchTab(event, 'dashboard')">
                <i class="fas fa-th-large"></i>
                <span>Dashboard</span>
            </button>
            <button class="nav-item nav-reports" onclick="switchTab(event, 'reports')">
                <i class="fas fa-chart-bar"></i>
                <span>Reports</span>
            </button>
            <button class="nav-item nav-wikitoca" onclick="switchTab(event, 'wikitoca')">
```

Substituir por (Dashboard seguido de AutoToca; Reports removido; o antigo `nav-autotoca` mais abaixo será removido no Step 2):

```html
            <button class="nav-item nav-dashboard" onclick="switchTab(event, 'dashboard')">
                <i class="fas fa-th-large"></i>
                <span>Dashboard</span>
            </button>
            <button class="nav-item nav-autotoca" onclick="switchTab(event, 'autotoca')">
                <i class="fas fa-wand-magic-sparkles"></i>
                <span>AutoToca</span>
            </button>
            <button class="nav-item nav-wikitoca" onclick="switchTab(event, 'wikitoca')">
```

- [ ] **Step 2: Remover a ocorrência antiga de `nav-autotoca`**

Localizar e remover o bloco antigo (estava entre Portifólio e Atividades, ~3383-3386):

```html
            <button class="nav-item nav-autotoca" onclick="switchTab(event, 'autotoca')">
                <i class="fas fa-wand-magic-sparkles"></i>
                <span>AutoToca</span>
            </button>
```

Resultado: Portifólio passa a ser seguido diretamente por Atividades.

- [ ] **Step 3: Verificar que há exatamente um `nav-autotoca` e nenhum `nav-reports`**

Run: `grep -c "nav-autotoca" public/index.html && grep -c "nav-reports" public/index.html`
Expected: primeira linha `1`, segunda linha `0`.

- [ ] **Step 4: Commit**

```bash
git add public/index.html
git commit -m "feat(ui): move AutoToca para abaixo de Dashboard e remove item Reports do menu"
```

---

## Task 2: Mover painéis de Reports para dentro da aba AutoToca

**Files:**
- Modify: `public/index.html` (aba `#autotoca` ~4085, aba `#reports` ~3987, `switchTab` ~5472, `toggleReportsPanel`/`toggleAutoTocaAutomation`)

- [ ] **Step 1: Adicionar os botões de Reports na barra de botões do AutoToca**

Localizar (na aba `#autotoca`, ~4110-4115):

```html
            <div style="display:flex; gap:10px; flex-wrap:wrap; margin-bottom:16px;">
                <button id="autoTocaBtn_chamado-juridico" class="btn btn-auto-mapping" onclick="toggleAutoTocaAutomation('chamado-juridico')"><span class="ai-star-icon">✦</span> Chamado Jurídico</button>
                <button id="autoTocaBtn_mala-direta" class="btn btn-auto-mapping" onclick="toggleAutoTocaAutomation('mala-direta')"><span class="ai-star-icon">✦</span> Mala Direta</button>
                <button class="btn btn-auto-mapping" onclick="openWhatsappUpdateWithWarning()"><span class="ai-star-icon">✦</span> WhatsApp Update</button>
                <button id="autoTocaBtn_sync-outlook" class="btn btn-auto-mapping" onclick="toggleAutoTocaAutomation('sync-outlook')"><span class="ai-star-icon">✦</span> Sync Outlook</button>
            </div>
```

Substituir por (adicionando os dois botões ex-Reports no início, mantendo os IDs originais `reportsBtn_*`):

```html
            <div style="display:flex; gap:10px; flex-wrap:wrap; margin-bottom:16px;">
                <button id="reportsBtn_preparar-reuniao" class="btn btn-auto-mapping" onclick="toggleReportsPanel('preparar-reuniao')"><i class="fab fa-linkedin" style="margin-right:5px;"></i> Preparar Reunião</button>
                <button id="reportsBtn_relationship-report" class="btn btn-auto-mapping" onclick="toggleReportsPanel('relationship-report')"><i class="fas fa-chart-line" style="margin-right:5px;"></i> Relationship Report</button>
                <button id="autoTocaBtn_chamado-juridico" class="btn btn-auto-mapping" onclick="toggleAutoTocaAutomation('chamado-juridico')"><span class="ai-star-icon">✦</span> Chamado Jurídico</button>
                <button id="autoTocaBtn_mala-direta" class="btn btn-auto-mapping" onclick="toggleAutoTocaAutomation('mala-direta')"><span class="ai-star-icon">✦</span> Mala Direta</button>
                <button class="btn btn-auto-mapping" onclick="openWhatsappUpdateWithWarning()"><span class="ai-star-icon">✦</span> WhatsApp Update</button>
                <button id="autoTocaBtn_sync-outlook" class="btn btn-auto-mapping" onclick="toggleAutoTocaAutomation('sync-outlook')"><span class="ai-star-icon">✦</span> Sync Outlook</button>
            </div>
```

- [ ] **Step 2: Recortar os dois painéis da aba `#reports` e colá-los no fim da aba `#autotoca`**

Na aba `#reports` (~3997-4033) recortar este bloco inteiro:

```html
            <div id="reportsPanel_preparar-reuniao" style="display:none; background:#fff; border:1px solid #e5e7eb; border-radius:12px; padding:16px; margin-bottom:16px;">
                ... (todo o conteúdo do painel Preparar Reunião) ...
            </div>
            <div id="reportsPanel_relationship-report" style="display:none;">
                <div id="reportsRelationshipContent"></div>
            </div>
```

Colar logo antes do fechamento `</div>` da aba `#autotoca` (após o último painel `autoTocaSyncOutlook`/`autoTocaMalaDireta` existente e antes do `</div>` que fecha `<div id="autotoca" class="tab-content">`). Manter os mesmos IDs.

- [ ] **Step 3: Remover a aba `#reports` agora vazia**

Localizar (~3987-4034) e remover o contêiner inteiro:

```html
        <!-- Reports Tab -->
        <div id="reports" class="tab-content">
            <div class="page-header">
                <h1>Reports</h1>
                <p>Relatórios executivos e ferramentas de análise comercial</p>
            </div>
            <div style="display:flex; gap:10px; flex-wrap:wrap; margin-bottom:16px;">
                <button id="reportsBtn_preparar-reuniao" ...></button>
                <button id="reportsBtn_relationship-report" ...></button>
            </div>
        </div>
```

(Os botões internos já foram recriados na aba AutoToca no Step 1; os painéis foram movidos no Step 2. A aba `#reports` deve sumir por completo.)

- [ ] **Step 4: Atualizar `switchTab` para inicializar Reports ao abrir AutoToca e remover o branch `reports`**

Localizar (~5470-5472):

```javascript
            else if (tabName === 'autotoca') { loadAutoToca(); _addinStartPolling(); _initOutlookAddinManifestUrl(); }

            else if (tabName === 'reports') loadReports();
```

Substituir por (chama `loadReports()` dentro do carregamento do AutoToca; remove o branch `reports`):

```javascript
            else if (tabName === 'autotoca') { loadAutoToca(); loadReports(); _addinStartPolling(); _initOutlookAddinManifestUrl(); }
```

- [ ] **Step 5: Unificar o fechamento de painéis entre `toggleReportsPanel` e `toggleAutoTocaAutomation`**

Para que abrir um painel de Reports feche os de automação e vice-versa, adicionar no início de `toggleReportsPanel` (logo após `if (!target) return;`, ~6455) o fechamento dos painéis de automação:

```javascript
            // Fecha também os painéis de automação do AutoToca
            ['autoTocaChamadoJuridico', 'autoTocaMalaDireta', 'autoTocaSyncOutlook'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.style.display = 'none';
            });
            ['autoTocaBtn_chamado-juridico', 'autoTocaBtn_mala-direta', 'autoTocaBtn_sync-outlook'].forEach(id => {
                const b = document.getElementById(id);
                if (b) { b.classList.remove('btn-secondary'); b.classList.add('btn-auto-mapping'); }
            });
```

E no início de `toggleAutoTocaAutomation` (~6406, logo após obter `panels`/antes de abrir), adicionar o fechamento dos painéis de Reports:

```javascript
            // Fecha também os painéis de Reports
            ['reportsPanel_preparar-reuniao', 'reportsPanel_relationship-report'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.style.display = 'none';
            });
            ['reportsBtn_preparar-reuniao', 'reportsBtn_relationship-report'].forEach(id => {
                const b = document.getElementById(id);
                if (b) { b.classList.remove('btn-secondary'); b.classList.add('btn-auto-mapping'); }
            });
```

(Verificar no `toggleAutoTocaAutomation` os IDs reais dos painéis de automação lendo o início da função; ajustar a lista `autoTocaSyncOutlook` etc. conforme os IDs existentes.)

- [ ] **Step 6: Verificar ausência de referências órfãs a `'reports'` como tab**

Run: `grep -n "switchTab(event, 'reports')\|=== 'reports'\|== 'reports'\|id=\"reports\"" public/index.html`
Expected: nenhuma linha (vazio). Se aparecer alguma, remover/ajustar.

- [ ] **Step 7: Verificação funcional**

Run: `python app.py` (background) e abrir `http://localhost:5000`.
- O menu não mostra "Reports"; "AutoToca" aparece logo abaixo de "Dashboard".
- Abrir AutoToca: os 6 botões aparecem; clicar em "Preparar Reunião" abre o painel e fecha os demais; clicar em "Relationship Report" carrega o seletor de conta (de `loadReports()`); clicar em "Chamado Jurídico" fecha os painéis de Reports.

- [ ] **Step 8: Commit**

```bash
git add public/index.html
git commit -m "feat(ui): move subfuncoes de Reports (Preparar Reuniao e Relationship Report) para AutoToca"
```

---

## Task 3: Backend — helpers de detecção de contato e conta

**Files:**
- Modify: `app.py` (inserir antes de `_linkedin_process_async`, ~13076)
- Test: script de smoke `scratchpad/test_linkedin_match.py`

- [ ] **Step 1: Escrever script de smoke que falha (funções ainda não existem)**

Criar `scratchpad/test_linkedin_match.py`:

```python
import app

# normalização de URL
assert app._normalize_linkedin_url('https://www.LinkedIn.com/in/Joao-Silva/') == 'linkedin.com/in/joao-silva'
assert app._normalize_linkedin_url('http://linkedin.com/in/joao-silva?trk=x#y') == 'linkedin.com/in/joao-silva'
assert app._normalize_linkedin_url('') == ''

# detecção: deve retornar tupla (contact|None, account|None) sem lançar
contact, account = app._linkedin_find_contact_and_account('https://linkedin.com/in/inexistente-xyz', 'Nome Inexistente XYZ')
assert contact is None or isinstance(contact, dict)
assert account is None or isinstance(account, dict)

print('OK')
```

- [ ] **Step 2: Rodar o script para confirmar a falha**

Run: `python scratchpad/test_linkedin_match.py`
Expected: FALHA com `AttributeError: module 'app' has no attribute '_normalize_linkedin_url'`.

- [ ] **Step 3: Implementar os helpers**

Inserir em `app.py` imediatamente antes de `def _linkedin_process_async` (~13076):

```python
def _normalize_linkedin_url(url):
    """Normaliza URL de LinkedIn para comparação: minúsculas, sem protocolo/www/querystring/trailing slash."""
    if not url:
        return ''
    u = str(url).strip().lower()
    u = u.split('?', 1)[0].split('#', 1)[0]
    u = re.sub(r'^https?://', '', u)
    u = re.sub(r'^www\.', '', u)
    return u.rstrip('/')


def _linkedin_find_contact_and_account(linkedin_url, contact_name):
    """Localiza o contato (por linkedin, depois por nome) e a conta mapeada vinculada
    via clients.company == accounts.name. Retorna (contact|None, account|None)."""
    conn = get_db()
    c = conn.cursor()
    contact = None
    norm = _normalize_linkedin_url(linkedin_url)
    if norm:
        c.execute("SELECT * FROM clients WHERE linkedin IS NOT NULL AND TRIM(linkedin) != ''")
        for row in c.fetchall():
            r = dict_from_row(row)
            if _normalize_linkedin_url(r.get('linkedin')) == norm:
                contact = r
                break
    if not contact and contact_name and contact_name.strip():
        c.execute("SELECT * FROM clients WHERE LOWER(TRIM(name)) = LOWER(TRIM(?)) ORDER BY id LIMIT 1",
                  (contact_name.strip(),))
        row = c.fetchone()
        if row:
            contact = dict_from_row(row)
    account = None
    if contact and (contact.get('company') or '').strip():
        c.execute("SELECT * FROM accounts WHERE LOWER(TRIM(name)) = LOWER(TRIM(?)) ORDER BY id LIMIT 1",
                  (contact['company'].strip(),))
        row = c.fetchone()
        if row:
            account = dict_from_row(row)
    conn.close()
    return contact, account


def _linkedin_resolve_account(account_id):
    """Carrega uma conta por id (usado quando o usuário força a conta no dropdown)."""
    try:
        aid = int(account_id)
    except (TypeError, ValueError):
        return None
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM accounts WHERE id = ? LIMIT 1", (aid,))
    row = c.fetchone()
    conn.close()
    return dict_from_row(row) if row else None
```

(`re` já é importado no topo de `app.py` — confirmar com `grep -n "^import re" app.py`.)

- [ ] **Step 4: Rodar o script para confirmar sucesso**

Run: `python scratchpad/test_linkedin_match.py`
Expected: imprime `OK`.

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat(linkedin): helpers de deteccao de contato e conta mapeada"
```

---

## Task 4: Backend — montar o contexto da conta

**Files:**
- Modify: `app.py` (inserir após os helpers da Task 3)
- Test: script de smoke `scratchpad/test_account_context.py`

- [ ] **Step 1: Escrever script de smoke que falha**

Criar `scratchpad/test_account_context.py`:

```python
import app

conn = app.get_db()
c = conn.cursor()
c.execute("SELECT * FROM accounts ORDER BY id LIMIT 1")
row = c.fetchone()
conn.close()

if not row:
    print('SKIP: nenhuma conta cadastrada para testar')
else:
    account = app.dict_from_row(row)
    ctx = app._linkedin_build_account_context(account, None)
    assert isinstance(ctx, dict)
    assert ctx['account']['name'] == account['name']
    assert 'market_moment' in ctx
    assert 'stefanini_services' in ctx and isinstance(ctx['stefanini_services'], list)
    assert ctx['contact_found'] is False
    assert ctx['relationship_summary'] is None
    print('OK')
```

- [ ] **Step 2: Rodar para confirmar a falha**

Run: `python scratchpad/test_account_context.py`
Expected: FALHA com `AttributeError: module 'app' has no attribute '_linkedin_build_account_context'` (ou `SKIP` se não houver conta — nesse caso criar uma conta de teste pela UI antes de prosseguir).

- [ ] **Step 3: Implementar o builder de contexto**

Inserir em `app.py` após `_linkedin_resolve_account`:

```python
def _linkedin_build_account_context(account, contact):
    """Monta o contexto da conta para o Preparar Reunião.
    Retorna dict com: account, market_moment, relationship_summary,
    stefanini_services, contact_found, contact_photo_url."""
    account_name = (account.get('name') or '').strip()

    # a) Momento de mercado (fresco a cada execução)
    market_moment = None
    try:
        market_moment = _relation_report_fetch_market_context(account_name)
    except Exception as e:
        logger.warning(f'[LinkedIn] Falha ao buscar momento de mercado: {e}')

    # c) Serviços Stefanini mapeados na conta
    stefanini_services = []
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""SELECT delivery_name, stf_owner, current_revenue_cents
                     FROM account_presences WHERE account_id = ?
                     ORDER BY delivery_name COLLATE NOCASE""", (account['id'],))
        for r in c.fetchall():
            row = dict_from_row(r)
            stefanini_services.append({
                'delivery_name': row.get('delivery_name') or '',
                'stf_owner': row.get('stf_owner') or '',
                'revenue': format_currency_br(row.get('current_revenue_cents')) if row.get('current_revenue_cents') else None,
            })
        conn.close()
    except Exception as e:
        logger.warning(f'[LinkedIn] Falha ao listar serviços Stefanini: {e}')

    # b) Resumo do relacionamento com o contato (só se o contato existir)
    relationship_summary = None
    contact_found = bool(contact)
    contact_photo_url = (contact.get('photo_url') or '').strip() if contact else ''
    if contact:
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute("""SELECT activity_date, type, description, notes
                         FROM activities WHERE client_id = ?
                         ORDER BY datetime(activity_date) DESC, id DESC LIMIT 20""", (contact['id'],))
            acts = [dict_from_row(r) for r in c.fetchall()]
            c.execute("""SELECT activity_date, description FROM account_activities
                         WHERE account_id = ?
                         ORDER BY datetime(activity_date) DESC, created_at DESC LIMIT 15""", (account['id'],))
            acc_acts = [dict_from_row(r) for r in c.fetchall()]
            conn.close()

            contact_lines = []
            for a in acts:
                txt = (a.get('description') or a.get('notes') or '').strip().replace('\n', ' ')
                if txt:
                    contact_lines.append(f"- {a.get('activity_date') or 's/data'} [{a.get('type') or 'atividade'}]: {txt[:240]}")
            account_lines = []
            for a in acc_acts:
                txt = (a.get('description') or '').strip().replace('\n', ' ')
                if txt:
                    account_lines.append(f"- {a.get('activity_date') or 's/data'}: {txt[:240]}")

            if contact_lines or account_lines:
                user_msg = (
                    f"Contato: {contact.get('name')} ({contact.get('position') or 'cargo não informado'}) "
                    f"da conta {account_name}.\n\n"
                    "HISTÓRICO DE ATIVIDADES DO CONTATO:\n"
                    + ('\n'.join(contact_lines) if contact_lines else '(sem registros diretos do contato)')
                    + "\n\nCONTEXTO DO RELACIONAMENTO DA CONTA:\n"
                    + ('\n'.join(account_lines) if account_lines else '(sem registros da conta)')
                    + "\n\nEscreva um resumo executivo do relacionamento com este contato em 2-4 frases, "
                    "priorizando o histórico do contato e complementando com o contexto da conta quando o "
                    "histórico direto for escasso. Não invente fatos não listados."
                )
                raw, _src = _iata_call_llm(
                    'Você é um assistente comercial. Responda em português (Brasil), apenas o resumo, sem markdown.',
                    user_msg,
                    'linkedin_relationship'
                )
                if raw and str(raw).strip():
                    relationship_summary = str(raw).strip()
        except Exception as e:
            logger.warning(f'[LinkedIn] Falha ao resumir relacionamento: {e}')

    return {
        'account': {'id': account['id'], 'name': account_name},
        'market_moment': market_moment,
        'relationship_summary': relationship_summary,
        'stefanini_services': stefanini_services,
        'contact_found': contact_found,
        'contact_photo_url': contact_photo_url,
    }
```

- [ ] **Step 4: Rodar para confirmar sucesso**

Run: `python scratchpad/test_account_context.py`
Expected: imprime `OK` (ou `SKIP` se não houver conta — então criar conta de teste e repetir).

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat(linkedin): builder de contexto da conta (mercado, relacionamento, servicos Stefanini)"
```

---

## Task 5: Backend — integrar contexto e fallback de foto no fluxo de summarize

**Files:**
- Modify: `app.py` — `linkedin_summarize()` (~13144) e `_linkedin_process_async` (~13076)

- [ ] **Step 1: Aceitar `account_id` no endpoint**

Em `linkedin_summarize()` (~13148-13162), após ler `extension_photo_url`, adicionar leitura de `account_id` e repassá-lo à thread:

```python
        extension_photo_url = (data.get('extension_photo_url') or '').strip()
        forced_account_id = data.get('account_id')

        if not linkedin_url and not profile_text:
            return jsonify({'error': 'Informe a URL do LinkedIn ou cole o texto do perfil.'}), 400

        task_id = uuid.uuid4().hex
        _bg_task_set(task_id, {'status': 'processing', 'step': 'Iniciando...', 'progress': 5})
        threading.Thread(
            target=_linkedin_process_async,
            args=(task_id, linkedin_url, profile_text, meeting_context, extension_photo_url, forced_account_id),
            daemon=True
        ).start()
```

- [ ] **Step 2: Atualizar a assinatura de `_linkedin_process_async`**

Trocar (~13076):

```python
def _linkedin_process_async(task_id, linkedin_url, profile_text, meeting_context, extension_photo_url):
```

por:

```python
def _linkedin_process_async(task_id, linkedin_url, profile_text, meeting_context, extension_photo_url, forced_account_id=None):
```

- [ ] **Step 3: Após o parse do resumo, detectar contato/conta, montar contexto e aplicar fallback de foto**

Em `_linkedin_process_async`, localizar o trecho do parse e da resolução de foto (~13094-13135). Substituir do `parsed = _linkedin_parse_summary(raw)` até a montagem do `result` por:

```python
        parsed = _linkedin_parse_summary(raw)
        contact_name = (parsed or {}).get('nome') or ''

        # Detecção de contato/conta
        contact, detected_account = _linkedin_find_contact_and_account(linkedin_url, contact_name)
        account = _linkedin_resolve_account(forced_account_id) if forced_account_id else detected_account

        _bg_task_set(task_id, {'step': 'Buscando foto do perfil...', 'progress': 70})
        photo_url = None
        photo_source = None
        if extension_photo_url:
            try:
                photo_url = _download_remote_image_to_uploads(extension_photo_url, prefix='linkedin-profile-ext')
                photo_source = 'extension_profile_photo'
            except Exception as e:
                logger.debug(f'[LinkedIn] Falha ao baixar foto da extensão: {e}')

        if not photo_url and linkedin_url:
            try:
                og_image = _linkedin_extract_og_image(linkedin_url)
                if og_image:
                    photo_url = _download_remote_image_to_uploads(og_image, prefix='linkedin-profile-og')
                    photo_source = 'linkedin_og_image'
            except Exception as e:
                logger.debug(f'[LinkedIn] Falha ao usar og:image: {e}')

        # Fallback (item d): foto do contato cadastrado no sistema
        if not photo_url and contact and (contact.get('photo_url') or '').strip():
            photo_url = contact['photo_url'].strip()
            photo_source = 'system_contact_photo'

        if not photo_url and parsed and parsed.get('nome'):
            try:
                nome = parsed['nome']
                cargo = parsed.get('cargo_atual', '')
                query = f'{nome} {cargo} foto perfil profissional'.strip()
                candidates = _find_image_candidates_on_web(query, limit=3)
                if candidates:
                    photo_url = _download_remote_image_to_uploads(candidates[0], prefix='linkedin-profile')
                    photo_source = 'web_search_fallback'
            except Exception as e:
                logger.debug(f'[LinkedIn] Falha ao buscar/baixar foto: {e}')

        # Contexto da conta (a/b/c)
        account_context = None
        if account:
            _bg_task_set(task_id, {'step': 'Analisando conta mapeada...', 'progress': 88})
            try:
                account_context = _linkedin_build_account_context(account, contact)
            except Exception as e:
                logger.warning(f'[LinkedIn] Falha ao montar contexto da conta: {e}')

        result = {
            'summary': parsed,
            'raw': raw if not parsed else None,
            'source': source,
            'fetched_from_url': fetched_text is not None,
            'limited_data': not data_is_rich,
            'photo_url': photo_url,
            'photo_source': photo_source,
            'account_context': account_context
        }
        _bg_task_set(task_id, {'step': 'Concluído!', 'progress': 100, 'status': 'done', 'result': result})
```

(Nota: este bloco substitui o `_bg_task_set(..., 'Buscando foto do perfil...', 'progress': 75)` original e toda a cadeia de resolução de foto + montagem de `result`, garantindo que não haja duplicação. Conferir que o `photo_source` map no frontend ganhará a chave `system_contact_photo` na Task 6.)

- [ ] **Step 4: Verificar compilação**

Run: `python -m py_compile app.py`
Expected: sem saída (sucesso).

- [ ] **Step 5: Smoke do endpoint (com o app rodando)**

Run (com `python app.py` ativo):
```bash
curl -s -X POST http://localhost:5000/api/linkedin/summarize -H "Content-Type: application/json" -d '{"profile_text":"Joao Silva, Diretor de TI na <conta-existente>. 15 anos de experiencia.","account_id":null}'
```
Expected: JSON `{"task_id":"..."}` com HTTP 202. Em seguida `curl http://localhost:5000/api/tasks/<task_id>` até `status:done`; o `result` deve conter a chave `account_context` (valor `null` se a conta não for detectada, ou objeto se detectada).

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat(linkedin): integra contexto da conta e fallback de foto do contato no summarize"
```

---

## Task 6: Frontend — enviar account_id e renderizar a seção de Contexto da Conta

**Files:**
- Modify: `public/index.html` — `gerarResumoLinkedIn` (~17473), `_renderLinkedInResult` (~17438), `_renderLinkedInSummary` (~17573), `photoSourceLabelMap` (~17580)

- [ ] **Step 1: Adicionar estado de conta forçada e enviá-la no request**

Junto às variáveis de estado do LinkedIn (~17433-17436), adicionar:

```javascript
        let atLinkedinForcedAccountId = null;
```

Em `gerarResumoLinkedIn`, no corpo do `fetch` para `/linkedin/summarize` (~17517-17522), adicionar o campo `account_id`:

```javascript
                    body: JSON.stringify({
                        linkedin_url: url,
                        profile_text: profileText,
                        meeting_context: meetingCtx,
                        extension_photo_url: shouldUseImportedPhoto ? atLinkedinLastImportedPhotoUrl : '',
                        account_id: atLinkedinForcedAccountId
                    })
```

- [ ] **Step 2: Registrar o label da nova fonte de foto**

Em `_renderLinkedInSummary`, no `photoSourceLabelMap` (~17580-17584), adicionar a entrada:

```javascript
            const photoSourceLabelMap = {
                extension_profile_photo: 'foto da extensão',
                linkedin_og_image: 'foto og:image',
                web_search_fallback: 'foto de busca web (fallback)',
                system_contact_photo: 'foto do contato no sistema'
            };
```

- [ ] **Step 3: Renderizar a seção de Contexto da Conta após o resumo**

Em `_renderLinkedInResult` (~17447-17448), trocar a chamada que monta o HTML do summary para anexar o contexto da conta:

De:
```javascript
            if (s) {
                resultArea.innerHTML = limitedDataWarning + _renderLinkedInSummary(s, data.source, data.fetched_from_url, data.photo_url, data.photo_source);
            } else if (data.raw) {
```

Para:
```javascript
            if (s) {
                resultArea.innerHTML = limitedDataWarning
                    + _renderLinkedInSummary(s, data.source, data.fetched_from_url, data.photo_url, data.photo_source)
                    + _renderAccountContext(data.account_context);
            } else if (data.raw) {
```

- [ ] **Step 4: Implementar `_renderAccountContext`**

Adicionar logo após `_renderLinkedInSummary` (após ~17657):

```javascript
        function _renderAccountContext(ac) {
            if (!ac || !ac.account) return '';
            const accName = _escHtml(ac.account.name || 'Conta');

            // Bloco a) momento de mercado
            const marketHtml = ac.market_moment
                ? `<p style="margin:0; font-size:13px; color:#374151; line-height:1.6;">${_escHtml(ac.market_moment)}</p>`
                : `<p style="margin:0; font-size:13px; color:#9ca3af;">Momento de mercado indisponível no momento.</p>`;

            // Bloco c) serviços Stefanini
            let svcHtml;
            if (Array.isArray(ac.stefanini_services) && ac.stefanini_services.length) {
                svcHtml = '<ul style="margin:0; padding-left:18px; font-size:13px; color:#374151;">'
                    + ac.stefanini_services.map(s => {
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
                        <h4 style="color:#047857; margin:0 0 8px; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;"><i class="fas fa-handshake" style="margin-right:6px;"></i>Relacionamento com o Contato</h4>
                        <p style="margin:0; font-size:13px; color:#374151; line-height:1.6;">${_escHtml(ac.relationship_summary)}</p>
                    </div>`;
            } else if (!ac.contact_found) {
                relHtml = `
                    <div style="margin-bottom:16px; background:#fffbeb; border:1px solid #fcd34d; border-radius:8px; padding:10px 12px;">
                        <span style="font-size:12px; color:#92400e;"><i class="fas fa-info-circle" style="margin-right:6px;"></i>Contato não vinculado a um contato cadastrado no sistema — exibindo apenas o contexto da conta.</span>
                    </div>`;
            }

            return `
            <div class="settings-card" style="margin-bottom:16px; border-left:4px solid #6366f1;">
                <div style="display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:14px; flex-wrap:wrap;">
                    <h3 style="color:#3730a3; margin:0; font-size:15px;"><i class="fas fa-building" style="margin-right:8px;"></i>Contexto da Conta: ${accName}</h3>
                </div>
                ${relHtml}
                <div style="margin-bottom:16px;">
                    <h4 style="color:#047857; margin:0 0 8px; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;"><i class="fas fa-chart-line" style="margin-right:6px;"></i>Momento de Mercado</h4>
                    ${marketHtml}
                </div>
                <div>
                    <h4 style="color:#047857; margin:0 0 8px; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;"><i class="fas fa-briefcase" style="margin-right:6px;"></i>O que temos na conta (Serviços Stefanini)</h4>
                    ${svcHtml}
                </div>
            </div>`;
        }
```

- [ ] **Step 5: Verificação funcional do fluxo completo**

Run: `python app.py` e abrir `http://localhost:5000` → AutoToca → Preparar Reunião.
- Colar um texto de perfil cujo nome/empresa case com um contato e conta cadastrados; gerar resumo.
- Esperado: abaixo do resumo executivo aparece o card "Contexto da Conta: <conta>" com Relacionamento (se houver atividades), Momento de Mercado e Serviços Stefanini.
- Testar um perfil de empresa não cadastrada: a seção de contexto não aparece (resumo normal).
- Testar um perfil cuja empresa case com conta mas o contato não exista: aparece o aviso curto + mercado + serviços, sem bloco de relacionamento.
- Testar fallback de foto: usar URL de LinkedIn de um contato cadastrado com `photo_url` mas sem foto resolvível; a foto do sistema deve aparecer com o badge "foto do contato no sistema".

- [ ] **Step 6: Commit**

```bash
git add public/index.html
git commit -m "feat(linkedin): renderiza secao de Contexto da Conta no Preparar Reuniao"
```

---

## Task 7: Verificação final e limpeza

**Files:**
- N/A (verificação)

- [ ] **Step 1: Compilar backend**

Run: `python -m py_compile app.py`
Expected: sucesso, sem saída.

- [ ] **Step 2: Conferir ausência de resíduos de Reports**

Run: `grep -n "tabName === 'reports'\|switchTab(event, 'reports')\|id=\"reports\"\|nav-reports" public/index.html`
Expected: vazio.

- [ ] **Step 3: Remover scripts de smoke temporários do scratchpad**

(Os scripts em `scratchpad/` não são versionados; nenhuma ação no git necessária. Confirmar que nada de teste temporário foi adicionado ao repositório com `git status`.)

Run: `git status --porcelain`
Expected: limpo (working tree sem alterações pendentes).

- [ ] **Step 4: Verificação funcional de regressão do AutoToca**

Run: app ativo → AutoToca → confirmar que Chamado Jurídico, Mala Direta, WhatsApp Update e Sync Outlook continuam abrindo/fechando corretamente e que alternar entre eles e os painéis de Reports fecha os demais.

---

## Self-Review (cobertura da spec)

- Parte 1 (menu + unificação): Tasks 1 e 2. ✔
- Parte 2a (momento de mercado fresco): Task 4 (`_relation_report_fetch_market_context`). ✔
- Parte 2b (resumo de relacionamento contato + contexto da conta): Task 4 (`_iata_call_llm`). ✔
- Parte 2c (Serviços Stefanini): Task 4 (`account_presences`). ✔
- Parte 2d (fallback de foto por LinkedIn→nome): Tasks 3 e 5. ✔
- Detecção automática + confirmação (dropdown): detecção em Tasks 3/5; o estado `atLinkedinForcedAccountId` e o envio de `account_id` ficam na Task 6. **Observação:** o seletor/dropdown visível de troca de conta pode ser adicionado como melhoria incremental reaproveitando `atLinkedinForcedAccountId` + re-chamada de `gerarResumoLinkedIn()`; a detecção automática já cobre o caso principal. Caso o dropdown visível seja requisito de aceite, adicionar um `<select>` no card de Contexto da Conta com `onchange` que seta `atLinkedinForcedAccountId` e chama `gerarResumoLinkedIn()`.
- Comportamento sem mapeamento (ocultar seção / aviso curto): Task 6 (`_renderAccountContext`). ✔
- Restrição "manter nome/header AutoToca": respeitada (nenhuma task altera o header). ✔
