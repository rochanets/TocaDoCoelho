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
    ]
    for field in required_text_fields:
        if not (data.get(field) or '').strip():
            errors.append(f'Campo obrigatório ausente: {field}')

    if data.get('tipoMinuta') not in VALID_TIPO_MINUTA:
        errors.append('tipoMinuta inválido.')

    # Contrato Original: se não houver upload, usa o genérico
    if not data.get('arquivosContratoOriginal'):
        data['arquivosContratoOriginal'] = [generic_contrato_file]

    # Minuta do Cliente: se não houver upload, usa o genérico
    if not data.get('arquivosMinutaCliente'):
        data['arquivosMinutaCliente'] = [generic_minuta_file]

    for file_field in ('arquivosAditivosAnteriores', 'arquivosContratoOriginal', 'arquivosMinutaCliente'):
        for file_path in data.get(file_field, []):
            if not os.path.exists(file_path):
                errors.append(f'Arquivo não encontrado para {file_field}: {file_path}')

    return {'ok': len(errors) == 0, 'errors': errors, 'normalized': data}
