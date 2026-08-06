# -*- coding: utf-8 -*-
"""Lógica pura da edição do texto de uma ata já salva (Task 9): casamento da
hierarquia recém-reestruturada pelo re-parse com a hierarquia antiga da MESMA
ata, para não perder vínculos com o CRM (`account_id`/`match_confirmed`) nem o
encadeamento com a ata anterior (`prev_opportunity_id`) só porque o usuário
reescreveu um nome. Sem Flask, sem SQLite, sem rede — extraído de
`routes/autotoca_iata.py` na revisão final para morar ao lado de
`reconcile.py` (mesma classe de problema: casar hierarquia velha com nova)."""

from .reconcile import match_account_name, normalize_name


def match_previous_items(old_items, new_items, name_of):
    """Casa cada item de `new_items` com o item correspondente de
    `old_items`, para carregar adiante campos que só existem no lado antigo
    através de um re-parse.

    Estratégia igual à do robô de formulário (`integrations/forms_robot.py`):
    nome normalizado primeiro (resiliente a reordenação), posição como
    fallback (resiliente a um typo corrigido ou nome levemente reescrito —
    mas arriscado se o item realmente virou outra coisa). O fallback só
    entra quando as duas listas têm o mesmo tamanho: é o sinal mais barato
    de "provavelmente o mesmo conjunto, só com nomes ajustados" sem tentar
    adivinhar mais que isso.

    Usada para GERENTE e OPORTUNIDADE — para CONTA, ver `match_previous_accounts`
    (revisão final, achado I1: o casamento de conta precisa da mesma escada de
    confiança usada por `reconcile`/`match_account_name`, não só nome exato).

    Devolve uma lista paralela a `new_items`: cada posição é `None` (sem
    candidato) ou uma tupla `(item_antigo, via)`, `via` sendo `'name'` ou
    `'position'` — o chamador usa `via` para decidir o que é seguro herdar
    do item antigo."""
    usados = set()
    old_by_norm = {}
    for old in old_items:
        norm = normalize_name(name_of(old))
        old_by_norm.setdefault(norm, old)

    resultado = [None] * len(new_items)
    for i, novo in enumerate(new_items):
        norm = normalize_name(name_of(novo))
        candidato = old_by_norm.get(norm)
        if candidato is not None and id(candidato) not in usados:
            resultado[i] = (candidato, 'name')
            usados.add(id(candidato))

    if len(old_items) == len(new_items):
        for i in range(len(new_items)):
            if resultado[i] is None and id(old_items[i]) not in usados:
                resultado[i] = (old_items[i], 'position')
                usados.add(id(old_items[i]))

    return resultado


def match_previous_accounts(old_accounts, new_accounts):
    """Casa contas antigas com contas novas para o mesmo propósito de
    `match_previous_items`, mas reaproveitando a escada de confiança de
    `match_account_name` (a mesma usada por `reconcile` para achar a conta
    anterior e por `_iata_sugerir_contas` para achar a conta do CRM): nome
    exato -> sem sufixo de forma jurídica -> similaridade (cutoff
    conservador).

    Achado da revisão final (I1): antes desta função, a edição casava conta
    só por nome EXATO, com fallback posicional só quando as duas listas têm o
    mesmo tamanho. `"Ambev"` (vínculo CONFIRMADO) virando `"Ambev S.A."` no
    texto editado — o caso mais comum do domínio — não batia no exato, e ao
    acrescentar uma terceira conta o tamanho das listas também deixava de
    bater, então nada casava: a confirmação humana evaporava em silêncio.
    Reusar `match_account_name` resolve o sufixo de forma jurídica do mesmo
    jeito que `reconcile` já resolve para a ata seguinte.

    Devolve uma lista paralela a `new_accounts`: cada posição é `None`, ou
    `(conta_antiga, via)`, `via` sendo:
    - `'name'`   — nome exato ou sem sufixo de forma jurídica (determinístico,
      confiança 'alta' de `match_account_name`): confiança suficiente para uma
      confirmação humana (`match_confirmed`) sobreviver;
    - `'fuzzy'`  — só similaridade (confiança 'media'): mesmo julgamento que
      `reconcile` usa para 'media', não é confiança suficiente para herdar
      uma confirmação — é sinalizado como palpite, igual à posição;
    - `'position'` — nenhum nome bateu (nem exato, nem sufixo, nem fuzzy); só
      a posição, plano B de sempre, com a mesma exigência de listas do mesmo
      tamanho de `match_previous_items`.
    """
    usados = set()
    catalogo = {}
    for old in old_accounts:
        norm = normalize_name(old.get('name'))
        if norm:
            # Primeira conta com este nome normalizado vence em caso de
            # colisão — mesmo critério usado em `_iata_sugerir_contas`.
            catalogo.setdefault(norm, old)

    resultado = [None] * len(new_accounts)
    for i, novo in enumerate(new_accounts):
        candidato, confidence = match_account_name(novo.get('name'), catalogo)
        if candidato is not None and id(candidato) not in usados:
            via = 'name' if confidence == 'alta' else 'fuzzy'
            resultado[i] = (candidato, via)
            usados.add(id(candidato))

    if len(old_accounts) == len(new_accounts):
        for i in range(len(new_accounts)):
            if resultado[i] is None and id(old_accounts[i]) not in usados:
                resultado[i] = (old_accounts[i], 'position')
                usados.add(id(old_accounts[i]))

    return resultado


def carregar_campos_anteriores(managers_antigos, managers_novos):
    """Depois de um re-parse bem-sucedido, preenche em `managers_novos` (in
    place) os campos que a IA não devolve porque não fazem parte do texto:
    `account_id`/`match_confirmed`/`match_confidence` de cada conta, e
    `previous_status`/`prev_opportunity_id`/`carried_over` de cada
    oportunidade — usando `match_previous_accounts` para CONTA e
    `match_previous_items` para GERENTE/OPORTUNIDADE.

    Achado da revisão de qualidade da Task 9: quando o casamento de uma
    CONTA veio por posição (o nome mudou e não há como confirmar que é a
    mesma conta), `match_confirmed` NUNCA é herdado como True — mesmo que a
    conta antiga estivesse confirmada via `/link`. Herdar cegamente
    trocaria vínculos de CRM quando o usuário renomeia duas contas do mesmo
    gerente e inverte a ordem em que digita. `account_id`/`match_confidence`
    continuam vindo como SUGESTÃO (o usuário pode reconfirmar em um clique em
    vez de procurar a conta de novo), só `match_confirmed` é zerado. A
    revisão final (I1) estende essa mesma guarda ao casamento por `'fuzzy'`:
    é julgamento por similaridade, não identidade confirmada, então também
    não pode fazer nascer uma confirmação.

    Cada oportunidade recebe também uma chave temporária `_old_own_id` (o
    id de banco da oportunidade ANTIGA desta mesma ata que foi casada, não
    o `prev_opportunity_id` que ela carrega) — usada pelo chamador para
    remapear referências de OUTRAS atas depois do DELETE+INSERT de
    `_iata_write_hierarchy` (ver rota `update_iata_body`). Precisa ser
    removida do dict antes de persistir em `ata_json`.

    Devolve um dict `{'accounts': [...], 'opportunities': [...], 'lost': [...]}`:
    - `accounts`/`opportunities`: um item por casamento feito por posição ou
      fuzzy, para a rota reportar ao usuário (nunca silencioso — mesmo
      princípio do campo `positional` no robô de formulário: "uma resposta na
      pergunta errada é pior que uma pergunta em branco");
    - `lost` (revisão final, I1 fix #2): uma conta antiga com vínculo
      CONFIRMADO que não casou com NADA na ata nova — nem nome, nem sufixo,
      nem fuzzy, nem posição (só acontece quando o tamanho das listas muda,
      ex.: a conta sumiu do texto ou uma conta nova foi acrescentada). Isso é
      perda de decisão humana e precisa aparecer separado dos casamentos por
      palpite acima, que ao menos preservam o account_id como sugestão — aqui
      não sobra nem isso."""
    positional = {'accounts': [], 'opportunities': [], 'lost': []}
    gerente_map = match_previous_items(
        managers_antigos, managers_novos, lambda m: m.get('name'))
    for manager, gm in zip(managers_novos, gerente_map):
        antigo_manager = gm[0] if gm else {}
        contas_antigas = (antigo_manager or {}).get('accounts') or []
        contas_novas = manager.get('accounts') or []
        conta_map = match_previous_accounts(contas_antigas, contas_novas)
        matched_old_ids = {id(cm[0]) for cm in conta_map if cm}

        for account, cm in zip(contas_novas, conta_map):
            antiga_conta = (cm[0] if cm else None) or {}
            via_conta = cm[1] if cm else None
            account['account_id'] = antiga_conta.get('account_id')
            account['match_confidence'] = antiga_conta.get('match_confidence')
            if via_conta == 'name':
                account['match_confirmed'] = bool(antiga_conta.get('match_confirmed'))
            else:
                account['match_confirmed'] = False
                if via_conta in ('position', 'fuzzy'):
                    positional['accounts'].append({
                        'manager': manager.get('name'), 'name': account.get('name'),
                        'previous_name': antiga_conta.get('name')})

            opps_antigas = antiga_conta.get('opportunities') or []
            opp_map = match_previous_items(
                opps_antigas, account.get('opportunities') or [], lambda o: o.get('name'))
            for opp, om in zip(account.get('opportunities') or [], opp_map):
                antiga_opp = (om[0] if om else None) or {}
                via_opp = om[1] if om else None
                opp['previous_status'] = antiga_opp.get('previous_status')
                opp['prev_opportunity_id'] = antiga_opp.get('prev_opportunity_id')
                opp['carried_over'] = bool(antiga_opp.get('carried_over'))
                opp['responsible'] = opp.get('responsible') or manager.get('name')
                opp['_old_own_id'] = antiga_opp.get('id')
                if via_opp == 'position':
                    positional['opportunities'].append({
                        'manager': manager.get('name'), 'account': account.get('name'),
                        'name': opp.get('name'), 'previous_name': antiga_opp.get('name')})

        # I1 fix #2: conta antiga confirmada que não casou com nada — nem
        # nome, nem sufixo, nem fuzzy, nem posição — perdeu a decisão humana
        # em silêncio. Reporta separado dos palpites acima.
        for old_account in contas_antigas:
            if old_account.get('match_confirmed') and id(old_account) not in matched_old_ids:
                positional['lost'].append({
                    'manager': manager.get('name'), 'name': old_account.get('name')})
    return positional


def flatten_opportunities(managers):
    """Achata `managers` na mesma ordem gerente -> conta -> oportunidade em
    que `_iata_write_hierarchy` insere (e `_iata_read_hierarchy` lê de
    volta, por `display_order`) — usado para alinhar índice a índice a
    oportunidade antiga com a nova linha física que a substitui."""
    saida = []
    for m in managers or []:
        for a in m.get('accounts') or []:
            for o in a.get('opportunities') or []:
                saida.append(o)
    return saida


def titulo_apos_edicao(titulo_anterior, titulo_novo_ia, body_editado):
    """Decide o título depois de um re-parse bem-sucedido.

    Achado da revisão: a IA reformula o título mesmo quando o usuário só
    corrigiu um typo no corpo ("Reunião Ambev - Q3" -> "Reunião comercial
    Ambev" sem nenhuma intenção do usuário de renomear a ata). Mantém o
    título anterior se ele (comparado por `normalize_name`, tolerante a
    acento/caixa/pontuação) ainda aparece em algum lugar do texto editado —
    só aceita o título novo da IA quando o antigo sumiu do corpo, sinal de
    que a mudança foi uma decisão deliberada do usuário ao reescrever o
    cabeçalho."""
    antigo_norm = normalize_name(titulo_anterior or '')
    corpo_norm = normalize_name(body_editado or '')
    if antigo_norm and antigo_norm in corpo_norm:
        return titulo_anterior
    return (titulo_novo_ia or '').strip() or titulo_anterior
