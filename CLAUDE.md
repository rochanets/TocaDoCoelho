# TocaDoCoelho — Guia para Claude Code (Vibecoding)

## Stack

- **Backend:** Python + Flask (`app.py`)
- **Frontend:** Vanilla JS + HTML em SPA única (`public/index.html`, ~8000+ linhas)
- **Banco:** SQLite via `get_db()`
- **Idioma do projeto:** Português (BR)

---

## LLM / IA — Como usar em novas features

### Helper principal: `_sai_simple_prompt(question)`

Sempre que uma feature precisar de uma resposta de LLM (geração de texto, extração de dados, classificação, etc.), **use `_sai_simple_prompt(question)`** como primeira opção. Ele usa o template SAI de prompt simples configurado no app.

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
