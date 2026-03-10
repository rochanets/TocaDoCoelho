import os


VALID_TIPO_MINUTA = {
    'Minuta padrão Stefanini - sem ajustes',
    'Minuta padrão Stefanini - com ajustes do cliente',
    'Minuta enviada pelo cliente (anexar no item 8)',
}


def validate_aditivo_payload(payload: dict, generic_contrato_file: str, generic_minuta_file: str) -> dict:
    errors = []
    data = dict(payload or {})

    required_text_fields = [
        'contaSelecionada',
        'enderecoFinalConfirmado',
        'numeroContratoSalesforce',
        'dataAssinaturaContratoOriginal',
    ]
    for field in required_text_fields:
        if not (data.get(field) or '').strip():
            errors.append(f'Campo obrigatório ausente: {field}')

    if data.get('tipoMinuta') not in VALID_TIPO_MINUTA:
        errors.append('tipoMinuta inválido.')

    if data.get('contratoOriginalModo') == 'upload_usuario':
        if not data.get('arquivosContratoOriginal'):
            errors.append('É obrigatório anexar arquivo no campo 8 (Contrato original).')
    else:
        data['arquivosContratoOriginal'] = [generic_contrato_file]

    if data.get('clienteEncaminhouMinuta') == 'Sim':
        if not data.get('arquivosMinutaCliente'):
            errors.append('Cliente encaminhou minuta = Sim exige upload do arquivo (campo 9).')
    else:
        data['arquivosMinutaCliente'] = [generic_minuta_file]

    for file_field in ('arquivosAditivosAnteriores', 'arquivosContratoOriginal', 'arquivosMinutaCliente'):
        for file_path in data.get(file_field, []):
            if not os.path.exists(file_path):
                errors.append(f'Arquivo não encontrado para {file_field}: {file_path}')

    return {'ok': len(errors) == 0, 'errors': errors, 'normalized': data}
