# -*- coding: utf-8 -*-
"""Contrato local dos campos do robô de Chamado Jurídico.

Este módulo não depende de Flask. Assim, o desktop legado e o Toca Companion
usam exatamente o mesmo mapeamento de perguntas sem importar o servidor web.
"""

from datetime import date


def build_chamado_juridico_fields(payload, files_by_field):
    """Converte o payload de negócio e os arquivos locais em campos do robô."""

    def paths(key):
        return [
            entry['stored_path']
            for entry in (files_by_field.get(key) or [])
            if entry.get('stored_path')
        ]

    def yes_no(key):
        return (
            'Sim'
            if (payload.get(key) or '').strip().lower() == 'sim'
            else 'Não'
        )

    minuta_tipo = (payload.get('minuta_tipo') or '').strip().lower()
    minuta_option_terms = (
        ['enviada pelo cliente']
        if minuta_tipo == 'cliente'
        else ['com ajustes do cliente']
    )

    # `q` é o fallback posicional 1-based. O item 21 não aparece de propósito:
    # essa pergunta nunca deve ser preenchida pelo Toca.
    fields = [
        {'key': 'origem', 'label': 'Origem da Solicitação', 'type': 'radio', 'q': 1,
         'terms': ['origem da solicitacao', 'origem'],
         'option_terms': ['Pedroso']},
        {'key': 'empresa_grupo', 'label': 'Empresa do Grupo Stefanini', 'type': 'radio', 'q': 2,
         'terms': ['empresa do grupo stefanini', 'grupo stefanini', 'empresa stefanini'],
         'option_terms': ['STEFANINI CONSULTORIA']},
        {'key': 'conta', 'label': 'Conta', 'type': 'text', 'q': 3,
         'terms': ['nome da conta', 'nome do cliente', 'conta', 'cliente'],
         'value': (payload.get('conta') or '').strip()},
        {'key': 'endereco', 'label': 'Endereço', 'type': 'text', 'q': 4,
         'terms': ['endereco'],
         'value': (payload.get('endereco') or '').strip()},
        {'key': 'minuta_tipo', 'label': 'Minuta/Contrato', 'type': 'radio', 'q': 5,
         'terms': ['minuta', 'contrato original enviado', 'origem da minuta'],
         'option_terms': minuta_option_terms},
        {'key': 'opp_salesforce', 'label': 'Opp Sales Force', 'type': 'text', 'q': 6,
         'terms': ['opp sales force', 'salesforce', 'numero da oportunidade'],
         'value': (payload.get('opp_salesforce') or '').strip() or '00000'},
        {'key': 'data_assinatura', 'label': 'Data de Assinatura do Contrato Original', 'type': 'date', 'q': 7,
         'terms': ['data de assinatura', 'data assinatura', 'assinatura do contrato original'],
         'value': (payload.get('data_assinatura') or '').strip() or date.today().isoformat()},
        {'key': 'aditivos_anteriores', 'label': 'Aditivos anteriores', 'type': 'file', 'q': 8,
         'terms': ['aditivos anteriores'],
         'file_paths': paths('aditivos_anteriores')},
        {'key': 'contrato_anterior', 'label': 'Contrato Anterior', 'type': 'file', 'q': 9,
         'terms': ['contrato anterior'],
         'file_paths': paths('contrato_anterior')},
        {'key': 'minuta_cliente', 'label': 'Há minuta do cliente?', 'type': 'file', 'q': 10,
         'terms': ['ha minuta do cliente', 'minuta do cliente'],
         'file_paths': paths('minuta_cliente')},
        {'key': 'havera_reajuste', 'label': 'Haverá Reajuste?', 'type': 'radio_yes_no', 'q': 11,
         'terms': ['havera reajuste'],
         'value': yes_no('havera_reajuste')},
        {'key': 'valores_reajuste', 'label': 'Descreva os valores de reajuste', 'type': 'text', 'q': 12,
         'terms': ['descreva os valores de reajuste', 'valores de reajuste'],
         'value': (payload.get('valores_reajuste') or '').strip()},
        {'key': 'aprovacao_reajuste', 'label': 'Aprovação de Reajuste Diferente do Contrato', 'type': 'file', 'q': 13,
         'terms': ['aprovacao de reajuste diferente do contrato', 'aprovacao de reajuste'],
         'file_paths': paths('aprovacao_reajuste')},
        {'key': 'houve_reoneracao', 'label': 'Houve reoneração?', 'type': 'radio_yes_no', 'q': 14,
         'terms': ['houve reoneracao', 'reoneracao'],
         'value': yes_no('houve_reoneracao')},
        {'key': 'aprovacao_reajuste_15', 'label': 'Aprovação de Reajuste (item 15)', 'type': 'file', 'q': 15,
         'terms': [],
         'file_paths': paths('aprovacao_reajuste')},
        {'key': 'inclui_novos_servicos', 'label': 'Inclui novos serviços?', 'type': 'radio_yes_no', 'q': 16,
         'terms': ['inclui novos servicos', 'novos servicos'],
         'value': yes_no('inclui_novos_servicos')},
        {'key': 'proposta_comercial_tecnica', 'label': 'Proposta comercial e técnica', 'type': 'file', 'q': 17,
         'terms': ['proposta comercial e tecnica', 'proposta comercial'],
         'file_paths': paths('proposta_comercial_tecnica')},
        {'key': 'e_prorrogacao_vigencia', 'label': 'É prorrogação de vigência?', 'type': 'radio_yes_no', 'q': 18,
         'terms': ['prorrogacao de vigencia', 'prorrogacao'],
         'value': yes_no('e_prorrogacao_vigencia')},
        {'key': 'vigencia_datas', 'label': 'Data inicial e final da vigência', 'type': 'text', 'q': 19,
         'terms': ['data inicial e final da vigencia', 'inicial e final da vigencia'],
         'value': (payload.get('vigencia_datas') or '').strip()},
        {'key': 'assinatura_plataforma', 'label': 'Assinatura pela plataforma Stefanini ou do cliente?',
         'type': 'radio_yes_no', 'q': 20,
         'terms': ['assinatura pela plataforma', 'plataforma stefanini ou do cliente'],
         'value': (
             'Sim'
             if (payload.get('assinatura_plataforma') or '').strip().lower() == 'stefanini'
             else 'Não'
         )},
        {'key': 'descricao_pedido', 'label': 'Descrição do pedido', 'type': 'text', 'q': 22,
         'terms': ['conte brevemente sobre o que se trata esse pedido', 'brevemente sobre o que se trata'],
         'value': (payload.get('descricao_pedido') or '').strip()},
    ]

    if yes_no('havera_reajuste') != 'Sim':
        fields = [field for field in fields if field['key'] != 'valores_reajuste']
    if yes_no('e_prorrogacao_vigencia') != 'Sim':
        fields = [field for field in fields if field['key'] != 'vigencia_datas']
    return fields
