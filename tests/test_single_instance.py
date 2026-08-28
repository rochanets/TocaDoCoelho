# -*- coding: utf-8 -*-
"""Guarda de instância única do servidor.

No Windows, o SO_REUSEADDR usado pelo servidor de desenvolvimento do
Werkzeug permite que duas instâncias façam bind na MESMA porta sem nenhum
erro — e qual delas atende cada conexão é indeterminado. Em 07/08/2026
quatro processos `launcher.py --serve` escutavam localhost:3000 ao mesmo
tempo, e uma instância antiga (com código desatualizado) atendeu as
requisições do usuário enquanto a instância nova subia "com sucesso".

Por isso o app precisa detectar, ANTES de subir, se alguém já responde na
porta — e recusar-se a iniciar em vez de virar uma segunda instância muda.
"""
import socket
import threading

import app as toca


def test_porta_ja_em_uso_detecta_listener_ativo():
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.bind(('127.0.0.1', 0))
    servidor.listen(1)
    porta = servidor.getsockname()[1]

    def aceitar_uma_conexao():
        # No Windows, fechar o socket enquanto esta thread está bloqueada em
        # accept() faz o accept() levantar WSAENOTSOCK (10038) — o pytest
        # reportaria como exceção não tratada de thread. Só acontece se a
        # conexão nunca chegar (ou seja, se o assert abaixo já falhou), então
        # aqui o erro é esperado e engolido.
        try:
            conexao, _ = servidor.accept()
        except OSError:
            return
        conexao.close()

    # aceita a conexão de teste em background para o create_connection completar
    aceitador = threading.Thread(target=aceitar_uma_conexao, daemon=True)
    aceitador.start()
    try:
        assert toca._porta_ja_em_uso(porta) is True
    finally:
        # a thread aceitadora precisa terminar ANTES do close(), senão o
        # close() corre com o accept() (ver comentário acima)
        aceitador.join(timeout=5)
        servidor.close()


def test_porta_livre_nao_acusa_uso():
    sonda = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sonda.bind(('127.0.0.1', 0))
    porta = sonda.getsockname()[1]
    sonda.close()  # porta agora livre (era efêmera, só nossa)

    assert toca._porta_ja_em_uso(porta) is False
