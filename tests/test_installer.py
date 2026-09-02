"""Guardas do installer.nsi.

Estes testes travam o que foi aprendido investigando o erro "Erro ao abrir o
arquivo pra gravação: ...\\_internal\\vcruntime140.dll", que aparecia em TODA
atualização. Nenhuma das duas invariantes abaixo é óbvia lendo o script, e
quebrar qualquer uma delas devolve o diálogo Anular/Repetir/Ignorar ao usuário
sem falhar nada no build.
"""
import re
from pathlib import Path

import pytest

NSI = Path(__file__).resolve().parents[1] / 'installer.nsi'


@pytest.fixture(scope='module')
def script():
    return NSI.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def codigo(script):
    """O script sem comentários.

    Os comentários do installer.nsi citam de propósito o que NÃO se deve usar
    (`Delete /REBOOTOK`, por exemplo), então checar proibições no texto cru
    falharia por causa da própria explicação.
    """
    return '\n'.join(linha.split(';', 1)[0] for linha in script.splitlines())


def test_libera_arquivos_em_uso_antes_de_extrair(script):
    """A liberação tem de rodar ANTES do primeiro `File`.

    O taskkill que já existia só resolve processos NOSSOS. O bloqueio real era
    de terceiro: um processo alheio (host de mensagens nativas de uma extensão
    do Chrome, no caso investigado) ficou com `_internal\\VCRUNTIME140.dll`
    mapeada de dentro da pasta de instalação e continuou com ela aberta depois
    de o Toca ser encerrado. Não há processo nosso para matar, então a única
    saída é renomear o arquivo preso antes de extrair. Se a chamada for
    movida para depois de um `File`, é a extração que descobre o bloqueio — e
    aí o usuário só tem o diálogo Anular/Repetir/Ignorar.
    """
    chamada = script.index('Call TocaLiberarArquivosEmUso')
    primeiro_file = min(
        m.start() for m in re.finditer(r'^\s*File\b', script, re.MULTILINE)
    )
    assert chamada < primeiro_file


def test_nao_usa_delete_rebootok(codigo):
    """`Delete /REBOOTOK` não funciona neste instalador.

    Agendar exclusão para o próximo boot escreve em
    `PendingFileRenameOperations`, que exige privilégio de administrador. Este
    instalador é per-user de propósito (`RequestExecutionLevel user`, ver o
    comentário sobre o UAC no topo do script), então a chamada volta com acesso
    negado (erro 5, medido na máquina onde o erro acontecia) e a limpeza que
    parecia agendada simplesmente não acontece. A limpeza das sobras
    `.toca-old<n>` é best-effort, na atualização seguinte.
    """
    assert '/REBOOTOK' not in codigo


def test_libera_binarios_de_internal(script):
    """`_internal` é onde o bloqueio acontece: DLL e .pyd têm de estar cobertos."""
    assert '!insertmacro TocaLiberarDir "$INSTDIR\\_internal" "*.dll"' in script
    assert '!insertmacro TocaLiberarDir "$INSTDIR\\_internal" "*.pyd"' in script


def test_ainda_encerra_o_app_e_o_waha(script):
    """A liberação por rename é rede de segurança, não substituto do kill.

    Renomear é o plano B para o que não conseguimos encerrar. Enquanto o app
    estiver vivo ele continua escrevendo no banco e na porta 3000, então matar
    TocaDoCoelho.exe e o node do WAHA-lite continua sendo o plano A.
    """
    assert 'taskkill /F /IM TocaDoCoelho.exe /T' in script
    assert 'Get-Process node' in script
