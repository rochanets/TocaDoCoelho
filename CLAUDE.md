# TocaDoCoelho — Guia para Claude Code (Vibecoding)

## Stack

- **Backend:** Python + Flask (`app.py`)
- **Frontend:** Vanilla JS + HTML em SPA única (`public/index.html`, ~8000+ linhas)
- **Banco:** SQLite via `get_db()`
- **Idioma do projeto:** Português (BR)

---

## LLM / IA — Como usar em novas features

### Ordem de chamada LLM — OpenRouter primeiro, SAI como fallback

Para qualquer feature que use LLM (geração de texto, análise, classificação, etc.), **a ordem padrão é: OpenRouter primeiro, SAI como fallback**. Só use SAI como primário se a feature exigir explicitamente.

```python
or_key = _resolve_setting('openrouter_api_key', 'OPENROUTER_API_KEY')
if or_key:
    # tenta OpenRouter primeiro
    ...
# fallback: SAI
raw = _sai_simple_prompt(prompt)
```

Veja `_iata_call_llm()` em `app.py` como exemplo completo desse padrão.

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

**Padrão frontend — barra verde com coelhinho 🐇:**
```javascript
// Modal deve ter #formArea e #progressArea separados
// _setProgress(pct, step) atualiza a barra
// Polling a cada 800ms até status === 'done' ou 'error'
// Coelhinho animado na ponta da barra (ver openIAtaModal() como exemplo)
```

A animação do coelhinho usa CSS keyframes injetados em `<head>` via `document.createElement('style')` (id único para não duplicar). Exemplo em `openIAtaModal()` em `index.html`.

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
- Timeout de 45 segundos

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

---

## Padrões do projeto

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
