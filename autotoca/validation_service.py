import os


VALID_TIPO_MINUTA = {
    'Minuta padrão Stefanini - sem ajustes',
    'Minuta padrão Stefanini - com ajustes do cliente',
    'Minuta enviada pelo cliente',
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

    # Se houver reajuste, validar campos relacionados
    if data.get('haveraReajusteValores') == 'Sim':
        # Índice de reajuste é obrigatório
        if not (data.get('indiceReajuste') or '').strip():
            errors.append('Campo obrigatório quando há reajuste: Informe o índice utilizado e valor pós reajuste.')
        
        # Aprovação do CEO é obrigatória no formulário, mas se não houver, usar genérico
        if not data.get('arquivosAprovacaoCEO'):
            data['arquivosAprovacaoCEO'] = [generic_minuta_file]

    for file_field in ('arquivosAditivosAnteriores', 'arquivosContratoOriginal', 'arquivosMinutaCliente', 'arquivosAprovacaoCEO'):
        for file_path in data.get(file_field, []):
            if not os.path.exists(file_path):
                errors.append(f'Arquivo não encontrado para {file_field}: {file_path}')

    return {'ok': len(errors) == 0, 'errors': errors, 'normalized': data}
