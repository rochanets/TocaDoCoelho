"""Chaves embarcadas no build (bundled_credentials.py).

Instalação nova não tem nada no banco nem no ambiente — sem a chave embarcada o
Account Planning morria em "A chave da Tavily não está configurada".
"""
import types

import app as toca


def _sem_banco_nem_ambiente(monkeypatch):
    monkeypatch.setattr(toca, '_resolve_setting', lambda *_a, **_k: '')


def test_pc_novo_usa_a_chave_embarcada(monkeypatch):
    _sem_banco_nem_ambiente(monkeypatch)
    monkeypatch.setattr(
        toca, '_bundled_credentials',
        types.SimpleNamespace(TAVILY_API_KEY='tvly-do-build'),
    )
    assert toca._tavily_api_key() == 'tvly-do-build'


def test_chave_do_usuario_tem_prioridade_sobre_a_embarcada(monkeypatch):
    monkeypatch.setattr(toca, '_resolve_setting', lambda *_a, **_k: 'tvly-do-usuario')
    monkeypatch.setattr(
        toca, '_bundled_credentials',
        types.SimpleNamespace(TAVILY_API_KEY='tvly-do-build'),
    )
    assert toca._tavily_api_key() == 'tvly-do-usuario'


def test_sem_modulo_embarcado_nao_quebra(monkeypatch):
    """Rodar do código-fonte sem bundled_credentials.py continua válido."""
    _sem_banco_nem_ambiente(monkeypatch)
    monkeypatch.setattr(toca, '_bundled_credentials', None)
    assert toca._tavily_api_key() == ''


def test_chave_embarcada_vazia_equivale_a_ausente(monkeypatch):
    _sem_banco_nem_ambiente(monkeypatch)
    monkeypatch.setattr(
        toca, '_bundled_credentials', types.SimpleNamespace(TAVILY_API_KEY='   '),
    )
    assert toca._tavily_api_key() == ''


def test_o_modelo_versionado_nao_carrega_chave_de_verdade():
    """Guarda contra commitar a chave: o repositório é público."""
    from pathlib import Path

    exemplo = Path(toca.__file__).resolve().parent / 'bundled_credentials.example.py'
    conteudo = exemplo.read_text(encoding='utf-8')
    assert "TAVILY_API_KEY = ''" in conteudo
    assert 'tvly-' not in conteudo.split('"""')[-1], 'chave real vazou para o modelo versionado'


def test_bundled_credentials_esta_no_gitignore():
    from pathlib import Path

    gitignore = (Path(toca.__file__).resolve().parent / '.gitignore').read_text(encoding='utf-8')
    assert 'bundled_credentials.py' in gitignore
