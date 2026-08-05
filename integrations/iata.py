# -*- coding: utf-8 -*-
"""Lógica pura do iAta: normalização, parsing da resposta da IA, reconciliação
com a ata anterior e renderização. Sem Flask, sem SQLite, sem rede — tudo aqui
é testável isoladamente."""

import difflib
import re
import unicodedata

SEM_UPDATE = 'Sem update nesta reunião'
GERENTE_NAO_IDENTIFICADO = 'Gerente não identificado'

# Acima deste ponto de similaridade dois nomes são considerados candidatos ao
# mesmo negócio — mas não match automático: quem decide é o resolver.
_LIMIAR_AMBIGUIDADE = 0.75


def normalize_name(value):
    """Minúsculo, sem acento, pontuação virando espaço, espaços colapsados."""
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r'[^0-9a-zA-Z]+', ' ', text.lower())
    return re.sub(r'\s+', ' ', text).strip()


def _index_anterior(previous_managers):
    """{(conta_norm, opp_norm): dados} + {conta_norm: (gerente, conta, [opps])}."""
    por_opp, por_conta = {}, {}
    for manager in (previous_managers or []):
        gerente = (manager.get('name') or '').strip() or GERENTE_NAO_IDENTIFICADO
        for account in (manager.get('accounts') or []):
            conta_norm = normalize_name(account.get('name'))
            if not conta_norm:
                continue
            opps = list(account.get('opportunities') or [])
            por_conta.setdefault(conta_norm, {
                'manager': gerente,
                'name': (account.get('name') or '').strip(),
                'account_id': account.get('account_id'),
                'opportunities': opps,
            })
            for opp in opps:
                chave = (conta_norm, normalize_name(opp.get('name')))
                por_opp.setdefault(chave, opp)
    return por_opp, por_conta


def reconcile(current_managers, previous_managers, resolver=None):
    """Casa a hierarquia extraída da reunião nova com a da ata anterior.

    - match exato por nome normalizado (conta + oportunidade) -> carrega status;
    - nenhum candidato -> oportunidade nova;
    - mais de um candidato parecido -> delega ao `resolver`, chamado UMA vez com
      a lista de pares ambíguos; sem resolver, vira nova com confiança 'baixa';
    - o que estava na anterior e não apareceu -> entra com `carried_over` e
      `update_text = SEM_UPDATE`.

    `resolver(pares) -> {indice_do_par: id_da_oportunidade_anterior | None}`.
    """
    por_opp, por_conta = _index_anterior(previous_managers)
    usados = set()
    pendentes_ambiguos = []  # (opp_saida, conta_norm, candidatos)
    resultado = []

    for manager in (current_managers or []):
        gerente = (manager.get('name') or '').strip() or GERENTE_NAO_IDENTIFICADO
        contas_saida = []
        for account in (manager.get('accounts') or []):
            conta_norm = normalize_name(account.get('name'))
            anterior_conta = por_conta.get(conta_norm) or {}
            opps_saida = []
            for opp in (account.get('opportunities') or []):
                nome = (opp.get('name') or '').strip()
                saida = {
                    'name': nome,
                    'update_text': (opp.get('update_text') or '').strip(),
                    'responsible': (opp.get('responsible') or '').strip() or gerente,
                    'previous_status': None,
                    'carried_over': False,
                    'prev_opportunity_id': None,
                    'match_confidence': None,
                }
                chave = (conta_norm, normalize_name(nome))
                exato = por_opp.get(chave)
                if exato is not None:
                    usados.add(chave)
                    saida['previous_status'] = (exato.get('update_text') or '').strip() or None
                    saida['prev_opportunity_id'] = exato.get('id')
                else:
                    candidatos = _candidatos_proximos(nome, anterior_conta.get('opportunities'))
                    if candidatos:
                        pendentes_ambiguos.append((saida, conta_norm, candidatos))
                opps_saida.append(saida)
            contas_saida.append({
                'name': (account.get('name') or '').strip(),
                'account_id': account.get('account_id') or anterior_conta.get('account_id'),
                'match_confidence': account.get('match_confidence'),
                'opportunities': opps_saida,
            })
        resultado.append({'name': gerente, 'accounts': contas_saida})

    _resolver_ambiguos(pendentes_ambiguos, resolver, usados)
    _anexar_nao_citados(resultado, por_conta, usados)
    return resultado


def _candidatos_proximos(nome, opps_anteriores):
    alvo = normalize_name(nome)
    if not alvo:
        return []
    achados = []
    for opp in (opps_anteriores or []):
        ratio = difflib.SequenceMatcher(None, alvo, normalize_name(opp.get('name'))).ratio()
        if ratio >= _LIMIAR_AMBIGUIDADE:
            achados.append(opp)
    return achados


def _resolver_ambiguos(pendentes, resolver, usados):
    if not pendentes:
        return
    if resolver is None:
        for saida, _conta_norm, _cands in pendentes:
            saida['match_confidence'] = 'baixa'
        return
    pares = [
        {'index': i, 'nome_novo': saida['name'],
         'candidatos': [{'id': c.get('id'), 'nome': c.get('name')} for c in cands]}
        for i, (saida, _cn, cands) in enumerate(pendentes)
    ]
    try:
        decisoes = resolver(pares) or {}
    except Exception:
        decisoes = {}
    for i, (saida, conta_norm, cands) in enumerate(pendentes):
        escolhido = decisoes.get(i)
        casado = next((c for c in cands if c.get('id') == escolhido), None)
        if casado is None:
            saida['match_confidence'] = 'baixa'
            continue
        saida['prev_opportunity_id'] = casado.get('id')
        saida['previous_status'] = (casado.get('update_text') or '').strip() or None
        usados.add((conta_norm, normalize_name(casado.get('name'))))


def _anexar_nao_citados(resultado, por_conta, usados):
    """Tudo que estava na ata anterior e não apareceu na reunião nova entra
    como carried_over — garantido por código, não pelo modelo."""
    por_gerente = {m['name']: m for m in resultado}
    for conta_norm, dados in por_conta.items():
        faltantes = [
            opp for opp in dados['opportunities']
            if (conta_norm, normalize_name(opp.get('name'))) not in usados
        ]
        if not faltantes:
            continue
        gerente = por_gerente.get(dados['manager'])
        if gerente is None:
            gerente = {'name': dados['manager'], 'accounts': []}
            por_gerente[dados['manager']] = gerente
            resultado.append(gerente)
        conta = next((a for a in gerente['accounts']
                      if normalize_name(a['name']) == conta_norm), None)
        if conta is None:
            conta = {'name': dados['name'], 'account_id': dados.get('account_id'),
                     'match_confidence': None, 'opportunities': []}
            gerente['accounts'].append(conta)
        for opp in faltantes:
            conta['opportunities'].append({
                'name': (opp.get('name') or '').strip(),
                'update_text': SEM_UPDATE,
                'responsible': (opp.get('responsible') or '').strip() or dados['manager'],
                'previous_status': (opp.get('update_text') or '').strip() or None,
                'carried_over': True,
                'prev_opportunity_id': opp.get('id'),
                'match_confidence': None,
            })
