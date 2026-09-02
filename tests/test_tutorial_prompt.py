"""Oferta do guia em PDF na abertura do sistema.

A regra que importa travar: fechar o pop-up **não** grava nada — só o
checkbox "não perguntar de novo" grava. Se o POST passasse a gravar sempre,
a oferta apareceria uma única vez na vida da instalação e ninguém notaria,
porque o pop-up "funciona" nos dois casos.
"""
import app as toca


def _url_do_pdf():
    return toca.Path(toca.app.static_folder) / 'assets' / 'tutorial' / \
        'Toca-do-Coelho-Primeiro-Acesso.pdf'


def test_oferta_aparece_em_instalacao_nova(client):
    resp = client.get('/api/config/tutorial-prompt')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['dismissed'] is False
    assert data['url'] == '/assets/tutorial/Toca-do-Coelho-Primeiro-Acesso.pdf'
    # o pop-up só é oferecido quando o arquivo existe no build
    assert data['show'] is data['available']


def test_fechar_sem_marcar_o_checkbox_nao_grava_nada(client):
    assert client.get('/api/config/tutorial-prompt').get_json()['dismissed'] is False

    resp = client.post('/api/config/tutorial-prompt/seen', json={})
    assert resp.status_code == 200
    assert resp.get_json()['dismissed'] is False

    # e também quando o checkbox vem explicitamente desmarcado
    resp = client.post('/api/config/tutorial-prompt/seen',
                       json={'dont_ask_again': False})
    assert resp.status_code == 200

    depois = client.get('/api/config/tutorial-prompt').get_json()
    assert depois['dismissed'] is False, 'a oferta deve voltar na próxima abertura'


def test_checkbox_marcado_encerra_a_oferta_de_vez(client):
    resp = client.post('/api/config/tutorial-prompt/seen',
                       json={'dont_ask_again': True})
    assert resp.status_code == 200
    assert resp.get_json()['dismissed'] is True

    depois = client.get('/api/config/tutorial-prompt').get_json()
    assert depois['dismissed'] is True
    assert depois['show'] is False
    # o arquivo continua acessível pelo card de Configurações
    assert depois['available'] is _url_do_pdf().is_file()


def test_pdf_esta_no_build_e_e_servido(client):
    caminho = _url_do_pdf()
    assert caminho.is_file(), (
        'o guia deve estar em public/assets/tutorial/ — é de lá que o '
        'PyInstaller o empacota (--add-data "public;public")'
    )
    resp = client.get('/assets/tutorial/Toca-do-Coelho-Primeiro-Acesso.pdf')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/pdf'


def test_sem_o_arquivo_nao_ha_oferta_nem_link(client, monkeypatch, tmp_path):
    """Build sem o PDF: nada de pop-up e nada de link 404 nas Configurações."""
    monkeypatch.setattr(toca.app, 'static_folder', str(tmp_path))
    data = client.get('/api/config/tutorial-prompt').get_json()
    assert data['available'] is False
    assert data['show'] is False
    assert data['size_mb'] == 0
