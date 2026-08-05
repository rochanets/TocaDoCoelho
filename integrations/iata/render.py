# -*- coding: utf-8 -*-
"""Renderização da ata em texto (markdown, Task 4) e e-mail (HTML, Task 5).
Sem Flask, sem SQLite, sem rede — puro stdlib, testável isoladamente."""

from .reconcile import GERENTE_NAO_IDENTIFICADO

# Task 3 decidiu deliberadamente preservar conta/oportunidade sem nome (uma
# extração ruidosa da IA ainda pode ter capturado update/responsável reais)
# em vez de descartar o bloco, e deixou a decisão de rótulo para a
# renderização. Uma linha em branco (bullet sem texto, `<strong></strong>`
# vazio) não deixa claro pro usuário que existe algo ali — por isso os dois
# renders (texto e e-mail) usam este rótulo em vez de string vazia.
CONTA_SEM_NOME = 'Conta sem nome'
OPORTUNIDADE_SEM_NOME = 'Oportunidade sem nome'


def _clean_null(value):
    v = str(value or '').strip()
    return None if not v or v.lower() in ('null', 'none', 'n/a', '-') else v


def render_markdown(header, managers, extras=None):
    """Renderiza a ata em texto plano com bullets aninhados: conta com `*`,
    oportunidade indentada, Update e Responsável mais indentados ainda."""
    header = header or {}
    linhas = [
        f"Título da Reunião: {header.get('title') or ''}",
        "Data e horário: " + ' '.join(
            p for p in [header.get('meeting_date') or '', header.get('meeting_time') or ''] if p
        ).strip(),
        "Participantes: " + ', '.join(
            (p.get('name') or '') for p in (header.get('participants') or []) if p.get('name')
        ),
        f"Tema: {header.get('topic') or ''}",
        '',
    ]

    for manager in (managers or []):
        linhas.append(f"Gerente Comercial: {manager.get('name') or GERENTE_NAO_IDENTIFICADO}")
        linhas.append('')
        for account in (manager.get('accounts') or []):
            linhas.append(f"  * {(account.get('name') or '').strip() or CONTA_SEM_NOME}")
            for opp in (account.get('opportunities') or []):
                status = (opp.get('previous_status') or '').strip()
                titulo = (opp.get('name') or '').strip() or OPORTUNIDADE_SEM_NOME
                linhas.append(f"     * {titulo}: {status}" if status else f"     * {titulo}")
                linhas.append(f"        * Update: {(opp.get('update_text') or '').strip()}")
                linhas.append(f"        * Responsável: {(opp.get('responsible') or '').strip()}")
            linhas.append('')

    extras = extras or {}
    for chave, titulo in (('agenda', 'Pauta'), ('decisions', 'Decisões')):
        itens = [str(i).strip() for i in (extras.get(chave) or []) if str(i).strip()]
        if itens:
            linhas.append(titulo)
            linhas.extend(f'  * {i}' for i in itens)
            linhas.append('')

    passos = [s for s in (extras.get('next_steps') or []) if isinstance(s, dict)]
    if passos:
        linhas.append('Próximos passos')
        for s in passos:
            prazo = _clean_null(s.get('deadline'))
            sufixo = f" (prazo: {prazo})" if prazo else ''
            linhas.append(
                f"  * {(s.get('action') or '').strip()} — "
                f"{(s.get('responsible') or 'A definir').strip()}{sufixo}"
            )
        linhas.append('')

    insights = [i for i in (extras.get('insights') or []) if isinstance(i, dict)]
    if insights:
        linhas.append('Insights de negócio')
        for i in insights:
            oferta = _clean_null(i.get('matched_offer')) or 'sem solução mapeada'
            obs = (i.get('observation') or '').strip()
            linhas.append(f"  * {(i.get('pain') or '').strip()} → {oferta}"
                          + (f" — {obs}" if obs else ''))
        linhas.append('')

    return '\n'.join(linhas).rstrip() + '\n'
