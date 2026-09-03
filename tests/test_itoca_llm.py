"""iToca — resiliência da chamada ao LLM.

Contexto (feedback do Toca v5.7.0.1, 03/09/2026): o usuário abriu o iToca e
recebeu, no lugar da resposta, `Erro na API SAI (HTTP 429): Template usage
limit exceeded.` — a cota do template SAI *dedicado* do iToca
(`itoca_sai_template_id`) tinha estourado, e `_itoca_call_sai_llm` levantava
`RuntimeError` na cara do usuário. O módulo inteiro fica inutilizável até a
cota virar, mesmo com o "Geral Claude" (cota própria) e o OpenRouter
disponíveis e ociosos.

O CLAUDE.md do projeto manda toda automação com IA usar `_llm_prompt`
(SAI → OpenRouter). O chat do iToca era o único caminho de IA que nunca foi
ligado nessa cascata, porque usa um template com dois campos de entrada
(`question` + `context_sources`) em vez do prompt simples.
"""

import json

import pytest

import app as toca


class _RespostaFalsa:
    """Dublê mínimo de `requests.Response` para o caminho do template SAI."""

    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text

    @property
    def ok(self):
        return 200 <= self.status_code < 300


@pytest.fixture()
def sai_configurado(client):
    """Grava a chave do template dedicado do iToca no banco de teste.

    Sem chave, `_itoca_call_sai_llm` nem tenta o template — devolve o resumo
    "sem LLM" e o caminho que este arquivo exercita nunca é alcançado.
    """
    conn = toca.get_db()
    conn.execute(
        'INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)',
        ('itoca_sai_api_key', 'chave-de-teste'),
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def contexto():
    return [{
        'table': 'accounts',
        'id': 7,
        'snippet': 'nome: Petrobras | classificacao: conta-alvo (target)',
        'search_text': 'petrobras',
    }]


def _post_que_falha(status_code, text):
    chamadas = []

    def _post(url, *args, **kwargs):
        chamadas.append(url)
        return _RespostaFalsa(status_code, text)

    return _post, chamadas


def test_cota_do_template_dedicado_estourada_cai_para_o_llm_prompt(
        monkeypatch, sai_configurado, contexto):
    """Um 429 no template dedicado deve escorregar para a cascata padrão."""
    post, chamadas = _post_que_falha(429, 'Template usage limit exceeded.')
    monkeypatch.setattr(toca.requests, 'post', post)

    perguntas = []

    def _llm_prompt_falso(question, **kwargs):
        perguntas.append(question)
        return json.dumps({
            'answer': 'A Petrobras é uma conta target com 1 registro.',
            'confidence_percent': 80,
            'needs_refinement': False,
            'refinement_hint': '',
        })

    monkeypatch.setattr(toca, '_llm_prompt', _llm_prompt_falso)

    resultado = toca._itoca_call_sai_llm('A Petrobras é target?', contexto)

    assert chamadas, 'o template dedicado deve ser tentado antes do fallback'
    assert resultado['answer'] == 'A Petrobras é uma conta target com 1 registro.'
    assert resultado['confidence_percent'] == 80
    assert resultado['llm_used'] is True
    # O fallback tem que levar a pergunta E o contexto — sem o contexto o LLM
    # responderia do nada, o que é pior do que o erro que estamos consertando.
    assert len(perguntas) == 1
    assert 'A Petrobras é target?' in perguntas[0]
    assert 'Petrobras' in perguntas[0]
    assert 'conta-alvo (target)' in perguntas[0]


def test_erro_de_conexao_no_template_dedicado_cai_para_o_llm_prompt(
        monkeypatch, sai_configurado, contexto):
    """Não é só 429: rede caída no host do SAI também tem que ter fallback."""
    def _post_explode(url, *args, **kwargs):
        raise toca.requests.exceptions.ConnectionError('sem rota para o host')

    monkeypatch.setattr(toca.requests, 'post', _post_explode)
    monkeypatch.setattr(
        toca, '_llm_prompt',
        lambda question, **kwargs: json.dumps({'answer': 'Resposta do fallback'}))

    resultado = toca._itoca_call_sai_llm('E agora?', contexto)

    assert resultado['answer'] == 'Resposta do fallback'
    assert resultado['llm_used'] is True


def test_fallback_aceita_resposta_em_texto_puro(
        monkeypatch, sai_configurado, contexto):
    """O OpenRouter no fim da cascata não é obrigado a devolver JSON."""
    post, _ = _post_que_falha(429, 'Template usage limit exceeded.')
    monkeypatch.setattr(toca.requests, 'post', post)
    monkeypatch.setattr(
        toca, '_llm_prompt',
        lambda question, **kwargs: 'A Petrobras está marcada como target.')

    resultado = toca._itoca_call_sai_llm('A Petrobras é target?', contexto)

    assert resultado['answer'] == 'A Petrobras está marcada como target.'
    assert resultado['llm_used'] is True


def test_falha_dos_dois_provedores_ainda_levanta_erro(
        monkeypatch, sai_configurado, contexto):
    """Sem nenhum provedor de pé, o erro tem que aparecer — não uma resposta
    inventada, nem um silêncio que o frontend exibiria como resposta vazia."""
    post, _ = _post_que_falha(429, 'Template usage limit exceeded.')
    monkeypatch.setattr(toca.requests, 'post', post)
    monkeypatch.setattr(toca, '_llm_prompt', lambda question, **kwargs: None)

    with pytest.raises(RuntimeError) as exc:
        toca._itoca_call_sai_llm('A Petrobras é target?', contexto)

    assert '429' in str(exc.value)


def test_template_dedicado_ok_nao_chama_o_fallback(
        monkeypatch, sai_configurado, contexto):
    """O template dedicado continua sendo o caminho principal: enquanto ele
    responde, a cascata de fallback não deve ser tocada (é ela que consome a
    cota compartilhada do resto do app)."""
    def _post_ok(url, *args, **kwargs):
        return _RespostaFalsa(200, json.dumps({
            'answer': 'Resposta do template dedicado',
            'confidence_percent': 90,
            'needs_refinement': False,
            'refinement_hint': '',
        }))

    monkeypatch.setattr(toca.requests, 'post', _post_ok)

    def _nao_deve_ser_chamado(*args, **kwargs):
        raise AssertionError('o fallback não deve ser usado quando o SAI responde')

    monkeypatch.setattr(toca, '_llm_prompt', _nao_deve_ser_chamado)

    resultado = toca._itoca_call_sai_llm('A Petrobras é target?', contexto)

    assert resultado['answer'] == 'Resposta do template dedicado'
    assert resultado['confidence_percent'] == 90
