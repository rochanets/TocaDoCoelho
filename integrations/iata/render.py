# -*- coding: utf-8 -*-
"""Renderização da ata em texto (markdown, Task 4) e e-mail (HTML, Task 5).
Sem Flask, sem SQLite, sem rede — puro stdlib, testável isoladamente."""

from html import escape as _escape

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


def _linhas_de_passos(passos):
    """Texto de cada item de 'Próximos passos'.

    Um item que não veio como dict (a IA às vezes devolve `["Enviar proposta
    até sexta"]` em vez do objeto com action/responsible/deadline) entra como
    texto cru em vez de sumir da ata — mesmo princípio do rótulo de conta sem
    nome: melhor exibir algo imperfeito do que descartar em silêncio."""
    saida = []
    for passo in (passos or []):
        if not isinstance(passo, dict):
            texto = str(passo).strip()
            if texto:
                saida.append(texto)
            continue
        prazo = _clean_null(passo.get('deadline'))
        sufixo = f" (prazo: {prazo})" if prazo else ''
        saida.append(
            f"{(passo.get('action') or '').strip()} — "
            f"{(passo.get('responsible') or 'A definir').strip()}{sufixo}"
        )
    return saida


def _linhas_de_insights(insights):
    """Texto de cada insight. Item fora do formato entra como texto cru, pelo
    mesmo motivo de `_linhas_de_passos`."""
    saida = []
    for insight in (insights or []):
        if not isinstance(insight, dict):
            texto = str(insight).strip()
            if texto:
                saida.append(texto)
            continue
        oferta = _clean_null(insight.get('matched_offer')) or 'sem solução mapeada'
        obs = (insight.get('observation') or '').strip()
        saida.append(f"{(insight.get('pain') or '').strip()} → {oferta}"
                     + (f" — {obs}" if obs else ''))
    return saida


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

    for titulo, itens in (('Próximos passos', _linhas_de_passos(extras.get('next_steps'))),
                          ('Insights de negócio', _linhas_de_insights(extras.get('insights')))):
        if itens:
            linhas.append(titulo)
            linhas.extend(f'  * {i}' for i in itens)
            linhas.append('')

    return '\n'.join(linhas).rstrip() + '\n'


# Estilo inline em cada elemento — clientes de e-mail (Outlook em particular)
# descartam <style> no <head> e ignoram indentação de texto puro, então o
# aninhamento visual só sobrevive como <ul>/<li> aninhado de verdade.
_ESTILO_BASE = "font-family:Segoe UI,Arial,sans-serif; font-size:14px; color:#111827;"
_ESTILO_UL = "margin:4px 0 4px 0; padding-left:22px;"
_ESTILO_LI = "margin:2px 0;"


def email_subject(header):
    """Assunto do e-mail da ata.

    O título vem de um LLM e pode conter quebra de linha. O envio é via
    Microsoft Graph (JSON), então não há injeção de cabeçalho SMTP a temer —
    mas um assunto multi-linha aparece truncado ou estranho nos clientes de
    e-mail, então colapsamos tudo em espaço.
    """
    header = header or {}
    titulo = _uma_linha(header.get('title')) or 'Ata de Reunião'
    data = _uma_linha(_clean_null(header.get('meeting_date')))
    return f"Ata — {titulo} — {data}" if data else f"Ata — {titulo}"


def _uma_linha(valor):
    return ' '.join(str(valor or '').split())


def render_email_html(header, managers, extras=None):
    """Renderiza a ata como HTML com `<ul>` aninhado de verdade e estilo
    inline (sem `<style>`), para sobreviver a clientes de e-mail que
    descartam CSS no `<head>`. Todo conteúdo vindo do LLM passa por
    `html.escape` antes de entrar no markup."""
    header = header or {}
    partes = [f'<div style="{_ESTILO_BASE}">']

    def campo(rotulo, valor):
        if valor:
            partes.append(
                f'<p style="margin:2px 0;"><strong>{_escape(rotulo)}:</strong> '
                f'{_escape(valor)}</p>'
            )

    campo('Título da Reunião', (header.get('title') or '').strip())
    campo('Data e horário', ' '.join(
        p for p in [header.get('meeting_date') or '', header.get('meeting_time') or ''] if p
    ).strip())
    campo('Participantes', ', '.join(
        (p.get('name') or '') for p in (header.get('participants') or []) if p.get('name')))
    campo('Tema', (header.get('topic') or '').strip())

    for manager in (managers or []):
        partes.append(
            f'<p style="margin:16px 0 4px;"><strong>Gerente Comercial:</strong> '
            f'{_escape(manager.get("name") or GERENTE_NAO_IDENTIFICADO)}</p>'
        )
        partes.append(f'<ul style="{_ESTILO_UL}">')
        for account in (manager.get('accounts') or []):
            nome_conta = (account.get('name') or '').strip() or CONTA_SEM_NOME
            partes.append(
                f'<li style="{_ESTILO_LI}"><strong>'
                f'{_escape(nome_conta)}</strong>'
            )
            partes.append(f'<ul style="{_ESTILO_UL}">')
            for opp in (account.get('opportunities') or []):
                status = (opp.get('previous_status') or '').strip()
                rotulo = _escape((opp.get('name') or '').strip() or OPORTUNIDADE_SEM_NOME)
                if status:
                    rotulo += ': ' + _escape(status)
                partes.append(f'<li style="{_ESTILO_LI}">{rotulo}')
                partes.append(f'<ul style="{_ESTILO_UL}">')
                partes.append(
                    f'<li style="{_ESTILO_LI}"><strong>Update:</strong> '
                    f'{_escape((opp.get("update_text") or "").strip())}</li>'
                )
                partes.append(
                    f'<li style="{_ESTILO_LI}"><strong>Responsável:</strong> '
                    f'{_escape((opp.get("responsible") or "").strip())}</li>'
                )
                partes.append('</ul></li>')
            partes.append('</ul></li>')
        partes.append('</ul>')

    extras = extras or {}
    for chave, titulo in (('agenda', 'Pauta'), ('decisions', 'Decisões')):
        itens = [str(i).strip() for i in (extras.get(chave) or []) if str(i).strip()]
        if itens:
            partes.append(f'<p style="margin:16px 0 4px;"><strong>{titulo}</strong></p>')
            partes.append(f'<ul style="{_ESTILO_UL}">')
            partes.extend(f'<li style="{_ESTILO_LI}">{_escape(i)}</li>' for i in itens)
            partes.append('</ul>')

    for titulo, itens in (('Próximos passos', _linhas_de_passos(extras.get('next_steps'))),
                          ('Insights de negócio', _linhas_de_insights(extras.get('insights')))):
        if itens:
            partes.append(f'<p style="margin:16px 0 4px;"><strong>{titulo}</strong></p>')
            partes.append(f'<ul style="{_ESTILO_UL}">')
            partes.extend(f'<li style="{_ESTILO_LI}">{_escape(i)}</li>' for i in itens)
            partes.append('</ul>')

    partes.append('</div>')
    return ''.join(partes)
