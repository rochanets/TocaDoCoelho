from datetime import datetime

STEFA_OPTION = 'STEFANINI CONSULTORIA E ASSESSORIA EM INFORMATICA S A'


def map_aditivo_input(payload: dict) -> dict:
    data = dict(payload or {})
    mapped = {
        'empresaGrupoStefanini': STEFA_OPTION,
        'contaSelecionada': (data.get('contaSelecionada') or '').strip(),
        'enderecoSedeEncontrado': (data.get('enderecoSedeEncontrado') or '').strip(),
        'enderecoFonte': (data.get('enderecoFonte') or '').strip(),
        'enderecoFinalConfirmado': (data.get('enderecoFinalConfirmado') or '').strip(),
        'tipoMinuta': (data.get('tipoMinuta') or '').strip(),
        'numeroContratoSalesforce': (data.get('numeroContratoSalesforce') or '').strip(),
        'dataContratoModo': (data.get('dataContratoModo') or 'informada').strip(),
        'dataAssinaturaContratoOriginal': (data.get('dataAssinaturaContratoOriginal') or '').strip(),
        'arquivosAditivosAnteriores': list(data.get('arquivosAditivosAnteriores') or []),
        'contratoOriginalModo': (data.get('contratoOriginalModo') or 'upload_usuario').strip(),
        'arquivosContratoOriginal': list(data.get('arquivosContratoOriginal') or []),
        'clienteEncaminhouMinuta': (data.get('clienteEncaminhouMinuta') or 'Não').strip(),
        'arquivosMinutaCliente': list(data.get('arquivosMinutaCliente') or []),
        'haveraReajusteValores': (data.get('haveraReajusteValores') or 'Não').strip(),
    }

    if mapped['dataContratoModo'] == 'nao_se_aplica':
        mapped['dataAssinaturaContratoOriginal'] = datetime.now().strftime('%d/%m/%Y')

    return mapped
