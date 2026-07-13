# TocaDoCoelho — Guia para Claude Code (Vibecoding)

## Stack

- **Backend:** Python + Flask (`app.py`)
- **Frontend:** Vanilla JS + HTML em SPA única (`public/index.html`, ~8000+ linhas)
- **Banco:** SQLite via `get_db()`
- **Idioma do projeto:** Português (BR)

---

## LLM / IA — Como usar em novas features

### Ordem de chamada LLM — REGRA DE DESENVOLVIMENTO: SAI primeiro, OpenRouter como fallback

Para qualquer automação com IA (geração de texto, análise, classificação, extração, etc.),
**a ordem obrigatória é: SAI primeiro, OpenRouter como fallback**.

**Única exceção:** perguntas que exigem busca ativa na internet (notícias, dados atuais de
mercado) — aí o OpenRouter (com plugin de web) vem primeiro, pois nenhum template SAI tem
acesso à web em tempo real.

**Use sempre o helper pronto `_llm_prompt()` em `app.py`** — ele já implementa a regra:

```python
raw = _llm_prompt("Pergunta livre aqui...", log_tag='MinhaFeature')          # SAI → OpenRouter
raw = _llm_prompt("Notícias recentes sobre...", log_tag='X', web=True)      # OpenRouter/web → SAI
```

Não escreva chamadas diretas ao OpenRouter/SAI em features novas — adicione parâmetros ao
`_llm_prompt` se precisar de algo que ele não cobre.

---

### Barra de progresso obrigatória para operações longas

**Toda operação que envolva LLM, upload de arquivo ou processamento que possa levar mais de 2 segundos DEVE ter barra de progresso com polling assíncrono.** Não bloquear o request HTTP — usar thread + task store.

**Padrão backend (igual ao portfolio/iAta):**
```python
_tasks = {}
_tasks_lock = threading.Lock()

def _task_set(task_id, updates): ...
def _task_get(task_id): ...
def _task_cleanup(task_id, delay=300): ...

def _process_async(task_id, ...):
    _task_set(task_id, {'step': 'Extraindo...', 'progress': 15})
    # ... processamento ...
    _task_set(task_id, {'step': 'Concluído!', 'progress': 100, 'status': 'done', 'result': ...})

@app.route('/api/.../process', methods=['POST'])
def start():
    task_id = uuid.uuid4().hex
    _task_set(task_id, {'status': 'processing', 'step': 'Iniciando...', 'progress': 5})
    threading.Thread(target=_process_async, args=(task_id, ...), daemon=True).start()
    return jsonify({'task_id': task_id}), 202

@app.route('/api/.../tasks/<task_id>', methods=['GET'])
def poll(task_id):
    return jsonify(_task_get(task_id))
```

**Padrão frontend — barra verde com o coelho verde correndo:**
```javascript
// Modal deve ter #formArea e #progressArea separados
// _setProgress(pct, step) atualiza a barra
// Polling a cada 800ms até status === 'done' ou 'error'
// Coelho verde correndo na ponta da barra (ver openIAtaModal() como exemplo)
```

**A animação padrão do coelho é o WebP transparente `/images/coelho-correndo.webp` com a classe global `.coelho-run`** (definida no `<style>` principal do `index.html`). NUNCA usar o emoji 🐇 (coelho branco genérico) nem keyframes de "pulinho":

```html
<!-- dentro do div da barra de progresso (track com position:relative e overflow:visible) -->
<img src="/images/coelho-correndo.webp" class="coelho-run" alt="">
```

O asset foi gerado a partir de `public/videos/Loading_Bunny.mp4` removendo o fundo preto e a marca d'água (script em `scripts/gerar_assets_coelho.py`). O mesmo coelho em pose estática está no `coelho_icon_transparent.ico` (ícone multi-tamanho 16–256px usado pelo exe, atalhos e bandeja).

---

### Helper principal: `_sai_simple_prompt(question)`

Sempre que uma feature precisar de uma resposta de LLM (geração de texto, extração de dados, classificação, etc.), use `_sai_simple_prompt(question)` como **fallback** após tentar OpenRouter. Ele usa o template SAI de prompt simples configurado no app.

```python
raw = _sai_simple_prompt("Pergunta livre aqui. Instrua o formato da resposta no próprio texto.")
# raw é str com a resposta do LLM, ou None se SAI não estiver configurado/falhar
```

**Características:**
- Lê `itoca_sai_api_key` e `itoca_sai_base_url` automaticamente das configurações do app
- Template ID padrão: `69bc155d7462bf7c702e9295` (setting `itoca_sai_simple_template_id`)
- Aceita apenas o campo `question` como entrada — coloque todo o contexto necessário dentro da pergunta
- Retorna `None` silenciosamente se SAI não estiver configurado (não lança exceção)
- Timeout de 45 segundos, com retry automático em HTTP 429 (rate limit)
- Ordem de tentativa: primeiro o template SAI dedicado **Geral Claude**
  (`itoca_sai_geral_claude_template_id` / `itoca_sai_geral_claude_api_key`, integração
  separada com cota própria), depois o template "simple prompt" compartilhado como fallback
- **Nenhum template SAI tem acesso à web em tempo real** — para perguntas que dependem de
  dados atuais/recentes (notícias, momento de mercado, etc.), use `_openrouter_web_prompt()`
  em vez de `_sai_simple_prompt()`

**Padrão de uso com JSON:**
```python
raw = _sai_simple_prompt(
    f"Dados da empresa '{nome}'. "
    "Retorne SOMENTE JSON válido: "
    '{"campo1": valor, "campo2": valor}. '
    "Use null para campos desconhecidos."
)
if raw:
    # parse com _try_parse_json ou json.loads + regex fallback
```

### Fallback: OpenRouter

Se `_sai_simple_prompt` retornar `None` (SAI não configurado), use OpenRouter como fallback:

```python
or_key = _resolve_setting('openrouter_api_key', 'OPENROUTER_API_KEY')
if or_key:
    or_settings = _load_app_settings_map(['openrouter_model', 'openrouter_site_url', 'openrouter_app_name'])
    model = (or_settings.get('openrouter_model') or 'stepfun/step-3.5-flash:free').strip()
    # POST para https://openrouter.ai/api/v1/chat/completions
    # headers: Authorization: Bearer {or_key}, HTTP-Referer, X-Title
    # body: {model, messages: [{role:system,...},{role:user,...}], temperature: 0.1}
```

Veja `_account_autofill_via_sai()` em `app.py` como exemplo completo do padrão SAI → OpenRouter.

### Outros templates SAI (não usar para features novas)

| Setting | Template ID | Uso |
|---|---|---|
| `itoca_sai_template_id` | `69ac3c87024adc2d2bdc19f5` | iToca chat (pergunta + context_sources) |
| `itoca_action_detector_template_id` | `69b1c662485ca1e93db65015` | Detecção de intenção do usuário |
| `itoca_sai_simple_template_id` | `69bc155d7462bf7c702e9295` | **Prompt simples — USE ESTE** |
| `itoca_sai_geral_claude_template_id` | `6a45658f1615d7b89d76c4ac` | Fallback automático do prompt simples (chave/cota próprias via `itoca_sai_geral_claude_api_key`) — não chamar diretamente, é usado internamente por `_sai_simple_prompt` |

---

## Padrões do projeto

### Diálogos de confirmação — NUNCA usar `confirm()` nativo

**Proibido:** `confirm(...)`, `window.confirm(...)` — abre janela padrão do sistema operacional, fora do tema visual.

**Obrigatório:** usar `await uiConfirm(mensagem, título)` — modal temático já existente no projeto.

```javascript
// ERRADO
if (!confirm('Excluir?')) return;

// CERTO — função deve ser async
if (!await uiConfirm('Deseja realmente excluir este item?', 'Excluir Item')) return;
```

O mesmo vale para `prompt()` nativo → usar `await uiPrompt(mensagem, valorDefault, título)`.

---

### Botões AI (AutoToca style)
```html
<button class="btn btn-auto-mapping btn-small" onclick="minhaFuncao()">
  <span class="ai-star-icon">✦</span> Nome do Botão
</button>
```

### Busca de imagens via Bing
```python
candidates = _find_image_candidates_on_web(f'{nome} logo empresa', limit=4)
# Retorna lista de URLs de imagens
```

### Upload de logo/foto de conta
- Arquivo: campo `logo` no FormData (multipart)
- URL remota: campo `autofill_logo_url` no FormData (baixa e salva localmente)
- Diretório: `ACCOUNT_UPLOAD_DIR` → `/uploads/accounts/`

### Configurações do app
```python
value = _resolve_setting('chave_no_db', 'NOME_ENV_VAR')
# Busca primeiro no banco (app_settings), depois na variável de ambiente
```

### Parsing de moeda (BRL → centavos)
```python
cents = parse_currency_to_cents("R$ 1.500,00")  # → 150000
texto = format_currency_br(150000)              # → "R$ 1.500,00"
```
