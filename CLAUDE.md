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

---

## Robô de preenchimento de formulário externo (Playwright) — estratégia validada

Padrão usado no robô do Chamado Jurídico (`integrations/forms_robot.py`, acionado
por `POST /api/autotoca/chamado-juridico/robot`) para preencher um Microsoft
Forms de produção sem nenhuma integração/API do lado do formulário. **Use este
padrão como ponto de partida para qualquer nova automação de formulário externo**
(outro Forms, Google Forms, SharePoint list, portal de terceiro sem API etc.).

### Princípio central: navegador visível, submissão genuína, humano no controle

O robô não tenta contornar o formulário via API/scraping — ele abre um Chromium
real controlado por Playwright, com a **mesma sessão de login do usuário**, e
interage com a página exatamente como uma pessoa faria. A resposta enviada é
uma submissão legítima. O robô **nunca clica em Enviar sozinho** — ele preenche
tudo, pulsa visualmente o botão final e devolve o controle para o usuário
revisar e concluir.

```python
context = pw.chromium.launch_persistent_context(profile_dir, channel='chrome', viewport=None, args=['--start-maximized'])
```

- **Perfil persistente** em disco (`launch_persistent_context`, não `launch()` +
  `new_context()`): o login (Microsoft, Google, SSO...) só acontece uma vez; nas
  execuções seguintes a sessão já está lá.
- **Detecta o navegador padrão do usuário** antes de abrir (no Windows, lê o
  registro `HKCU\...\UrlAssociations\https\UserChoice\ProgId`) e cai para Chrome
  → Edge → Chromium embutido do Playwright, nessa ordem. Nunca hardcode um
  navegador só porque "geralmente funciona" — o usuário espera ver o navegador
  que ele já usa no dia a dia.
- **Janela maximizada, sem viewport fixo** (`viewport=None` + `--start-maximized`)
  quando visível. Um viewport pequeno corta o fim de páginas longas sem o
  usuário perceber que dava pra rolar — especificamente, o botão Enviar pode
  ficar fora da área visível.

### Abrir em uma aba da sessão já aberta (opcional)

Por padrão, o robô usa o perfil persistente próprio do AutoToca, porque uma
instância comum do Chrome/Edge não permite que outro processo se conecte às
abas existentes. Quando o navegador do usuário é iniciado com depuração remota,
é possível reaproveitar a sessão autenticada definindo
`TOCA_ROBOT_CDP_URL=http://127.0.0.1:9222`. Nesse modo o robô abre uma nova aba
no contexto já conectado e não fecha o navegador do usuário ao terminar.
Isso é opt-in: não se deve tentar anexar automaticamente a portas locais ou
ao perfil pessoal sem que o usuário tenha habilitado a depuração.

No módulo **Reembolsos**, a forma preferencial de reutilizar o Chrome já aberto
é a extensão AutoToca **0.9.2 ou superior**. O frontend entrega à extensão apenas
o identificador opaco da tarefa; a extensão abre o e-Reembolso em uma nova aba,
mantém a tarefa pendente durante o login e busca os dados/anexos na API local
depois da autenticação. Se a extensão estiver ausente ou desatualizada, o usuário
deve confirmar explicitamente antes do fallback para a janela persistente do
Playwright. Uma instância comum do Chrome não pode ser anexada pelo Playwright
depois de aberta sem CDP ou extensão.

### Localização de campo: texto normalizado primeiro, posição numérica como fallback

Cada campo é localizado pelo texto da pergunta **normalizado** (sem acento,
minúsculo, pontuação virando espaço) contido no bloco da pergunta inteira —
resiliente a reordenação do formulário. Quando nenhum termo bate com nada na
página (a redação real não é conhecida, ou o campo replica outro), cai para a
posição numérica (`q`, 1-based) informada por quem chama, e isso é **reportado
separadamente** (`positional`) para o usuário conferir visualmente — uma
resposta na pergunta errada é pior do que uma pergunta deixada em branco.

### Seleção de opção (radio/checkbox): delegue ao navegador, não adivinhe o DOM

**Lição mais importante desta implementação.** A primeira tentativa extraía o
texto de cada opção "na mão" (`aria-label`, `closest('label')`,
`el.parentElement.innerText` etc.) — e quebrou de verdade: quando as opções de
um grupo de rádio são elementos-irmãos no DOM (o padrão mais comum), pegar
`parentElement.innerText` devolve o texto de **todas** as opções juntas, então
qualquer termo bate sempre na primeira opção da lista, não na correta.

A correção definitiva foi trocar para o mecanismo de acessibilidade nativo do
Playwright, que delega ao próprio motor do navegador (o mesmo algoritmo que a
árvore de acessibilidade do Chromium usa) o cálculo do nome de cada opção:

```python
target = question.get_by_role('radio', name=term).first  # substring literal, case-insensitive
```

**Atenção:** esse matcher compara por **substring literal**, sem normalizar
acento/pontuação — diferente do matching de pergunta acima. `'nao'` nunca bate
com `"Não"`; use `'Não'`. `'comercial pedroso'` nunca bate com `"Comercial -
Pedroso"` (o traço quebra o substring); use um fragmento sem pontuação, tipo
`'Pedroso'`.

### Todo campo escrito precisa de verificação + nova tentativa

Nunca assuma que `.click()` + `.fill()` + `.type()` funcionou só porque não
lançou exceção. Depois de escrever, **leia de volta** e compare:

```python
target.fill(''); target.type(valor, delay=30)
if target.input_value().strip() != valor.strip():
    # tenta mais uma vez após uma pequena espera; se persistir, levanta erro
    # específico (não silencioso) para aparecer no relatório final
```

O mesmo vale para rádio: depois do clique, confira `aria-checked === 'true'`
(ou `.checked` para `<input>` nativo) antes de considerar concluído.

### Data: tente digitar antes de simular clique em calendário

Campos de data no Fluent UI/Forms costumam *parecer* somente-calendário (o
input tem `readonly` implícito ou o placeholder sugere isso), mas digitar
`dd/MM/yyyy` direto no campo pode funcionar mesmo assim. **Tente digitação
primeiro, caia para navegação por clique no calendário só se a verificação do
valor digitado falhar** — a navegação por calendário (abrir popup, ler
mês/ano exibido, clicar próximo/anterior até bater, clicar no dia) é bem mais
frágil e deve ser o plano B, não o A.

### Diagnóstico: erros específicos, sem precisar reproduzir às cegas

Cada falha de campo guarda o suficiente para diagnosticar **sem acesso ao
navegador ao vivo**: `errors` traz mensagem específica por campo (opções
vistas na tela, texto do cabeçalho do calendário, valor que realmente ficou
no input), e o resultado completo (`filled`/`positional`/`unmatched`/`errors`)
vai para o `app.log` via `logger.info(...)` — não só os acessos HTTP do
Flask. Sem isso, um bug relatado pelo usuário fica impossível de investigar
remotamente.

### Overlay visual: mostre o que o robô está fazendo

Um cursor animado (injetado via `page.evaluate()`, `position:fixed` com
`z-index` máximo e `pointer-events:none`) se move até cada campo antes de
preenchê-lo, e um badge fixo no rodapé narra o passo atual. Isso não é
cosmético: é o que dá ao usuário confiança de que pode acompanhar e
interromper a qualquer momento, em vez de um processo às escuras. Para um
cursor customizado com transparência real (não um emoji), use **APNG**, não
WebM/VP9 — o encoder `libvpx-vp9` do ffmpeg estático (`imageio-ffmpeg`) não
preserva o canal alfa neste ambiente mesmo com `-pix_fmt yuva420p`; APNG
preserva alpha de forma confiável e o Chromium (o motor por trás do
Playwright) tem suporte nativo sólido.

### Teste contra uma réplica local, não só contra produção

Este ambiente de execução não tem acesso de rede de saída para abrir a
página de produção (só ferramentas de linha de comando como `curl`
conseguem — Chromium/Playwright não). A validação real veio de reproduzir a
estrutura DOM da página-alvo (perguntas, rádios, data, upload) num HTML
estático servido localmente e rodar o mesmo código do robô contra ele,
headless, antes de cada correção subir para o usuário testar de verdade.
Isso pegou bugs reais (a colisão de texto do rádio, a corrida de tempo do
"envio automático" no próprio fixture de teste) sem precisar de uma rodada
completa de feedback do usuário a cada iteração.
