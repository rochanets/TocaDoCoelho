# -*- coding: utf-8 -*-
"""Normalização de nomes e reconciliação da hierarquia extraída de uma
reunião com a da ata anterior. Sem Flask, sem SQLite, sem rede — tudo aqui é
testável isoladamente. Task 2 do plano iAta."""

import difflib
import logging
import re
import unicodedata

SEM_UPDATE = 'Sem update nesta reunião'
GERENTE_NAO_IDENTIFICADO = 'Gerente não identificado'

# Acima deste ponto de similaridade dois nomes de OPORTUNIDADE são
# considerados candidatos ao mesmo negócio — mas não match automático: quem
# decide é o resolver.
_LIMIAR_AMBIGUIDADE = 0.75

# Cutoff para casar CONTA anterior por similaridade quando não há match exato
# de nome normalizado (I2). Deliberadamente alto: um falso positivo aqui
# funde duas contas de fato diferentes no mesmo bloco da ata, o que é pior
# do que exibi-las duplicadas — preferimos perder alguns matches de grafia
# muito distinta a arriscar fundir contas distintas.
_LIMIAR_CONTA = 0.85

# Prefixo de chave sintética para contas cujo nome não normaliza para nada
# (nome vazio/só pontuação vindo de uma extração ruidosa da IA). Cada
# ocorrência recebe uma chave própria — nunca colide com uma conta nomeada
# — para que a conta ainda seja recuperada como carried over (C3) em vez de
# simplesmente descartada.
_SYNTHETIC_ACCOUNT_PREFIX = '\x00__conta_sem_nome__'

# Tokens de forma jurídica removidos do FIM do nome normalizado de uma conta
# para casamento por sufixo (ex.: "Ambev S.A." == "Ambev"). Isto é
# deliberadamente restrito a forma jurídica — não é um subset match genérico:
# "Vale" e "Vale Verde" continuam contas diferentes porque nenhuma delas
# termina com um destes tokens. Ordenado por número de tokens, do maior para
# o menor, para que "s a s" seja tentado antes de "s a".
_SUFIXOS_FORMA_JURIDICA = (
    ('s', 'a', 's'),
    ('s', 'a'),
    ('sa',),
    ('ltda',),
    ('me',),
    ('eireli',),
    ('epp',),
)

_logger = logging.getLogger(__name__)


def _strip_legal_suffix(conta_norm):
    """Remove um único token/sequência de forma jurídica do fim do nome
    normalizado, se houver — nunca deixa o resultado ficar vazio (se o nome
    inteiro for o sufixo, a regra é ignorada e o nome original é devolvido)."""
    if not conta_norm:
        return conta_norm
    tokens = conta_norm.split(' ')
    for sufixo in _SUFIXOS_FORMA_JURIDICA:
        n = len(sufixo)
        if len(tokens) > n and tuple(tokens[-n:]) == sufixo:
            return ' '.join(tokens[:-n])
    return conta_norm


def normalize_name(value):
    """Minúsculo, sem acento, pontuação virando espaço, espaços colapsados."""
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r'[^0-9a-zA-Z]+', ' ', text.lower())
    return re.sub(r'\s+', ' ', text).strip()


def _index_anterior(previous_managers):
    """Indexa a ata anterior para consulta durante a reconciliação.

    Retorna `(por_opp, por_conta)`:
    - `por_conta`: chave de conta -> {'manager', 'name', 'account_id',
      'opportunities': [{'idx': int, 'data': opp}, ...]}. A chave é o nome de
      conta normalizado, ou uma chave sintética para contas sem nome (C3).
    - `por_opp`: (chave_conta, nome_opp_normalizado) -> lista de
      `{'idx': int, 'data': opp}` — lista, não item único, porque duas
      oportunidades homônimas na mesma conta são um cenário real (C2) e não
      podem se fundir numa só.

    Cada oportunidade anterior recebe um `idx` sequencial único (não é o
    `id` do banco, que pode ser `None`) — é essa identidade interna, e não o
    nome, que controla o que já foi "consumido" durante a reconciliação.
    """
    por_opp, por_conta = {}, {}
    idx_counter = 0
    contador_sem_nome = 0
    for manager in (previous_managers or []):
        gerente = (manager.get('name') or '').strip() or GERENTE_NAO_IDENTIFICADO
        for account in (manager.get('accounts') or []):
            conta_norm = normalize_name(account.get('name'))
            if conta_norm:
                conta_key = conta_norm
            else:
                conta_key = f'{_SYNTHETIC_ACCOUNT_PREFIX}{contador_sem_nome}'
                contador_sem_nome += 1

            entry = por_conta.get(conta_key)
            if entry is None:
                # C1: a mesma conta pode aparecer sob gerentes diferentes na
                # ata anterior (ela pode ter trocado de dono entre reuniões).
                # Mesclamos as oportunidades de todas as ocorrências em vez
                # de perder as do segundo bloco — mantendo o primeiro
                # gerente visto como dono "de fato" só para fins de
                # posicionamento de itens carried over.
                entry = {
                    'manager': gerente,
                    'name': (account.get('name') or '').strip(),
                    'account_id': account.get('account_id'),
                    'match_confidence': account.get('match_confidence'),
                    # Um vínculo confirmado pelo usuário (Task 8, rota /link)
                    # precisa sobreviver na hierarquia indexada da ata
                    # anterior — é essa entrada que `reconcile` consulta pra
                    # propagar o vínculo pra ata nova.
                    'match_confirmed': bool(account.get('match_confirmed')),
                    'opportunities': [],
                }
                por_conta[conta_key] = entry
            else:
                if not entry.get('account_id') and account.get('account_id'):
                    entry['account_id'] = account.get('account_id')
                # C1 (mesma conta sob gerentes diferentes): uma confirmação
                # em qualquer ocorrência vence — não deixamos uma segunda
                # ocorrência não confirmada apagar a confirmação já vista.
                if account.get('match_confirmed') and not entry.get('match_confirmed'):
                    entry['match_confirmed'] = True
                    entry['account_id'] = account.get('account_id') or entry.get('account_id')
                    entry['match_confidence'] = account.get('match_confidence') or entry.get('match_confidence')

            for opp in (account.get('opportunities') or []):
                item = {'idx': idx_counter, 'data': opp}
                idx_counter += 1
                entry['opportunities'].append(item)
                chave = (conta_key, normalize_name(opp.get('name')))
                por_opp.setdefault(chave, []).append(item)
    return por_opp, por_conta


def _match_previous_account_key(conta_norm, por_conta, contas_nomeadas_norms, indice_sem_sufixo):
    """Acha a chave, em `por_conta`, da conta anterior correspondente à
    conta atual `conta_norm`, em ordem de confiança decrescente:

    (a) nome normalizado idêntico;
    (b) nome sem sufixo de forma jurídica idêntico (determinístico — não é
        fuzzy, é remover um token conhecido como "s a"/"ltda"/etc. do fim);
    (c) similaridade com cutoff conservador — ver `_LIMIAR_CONTA`.
    """
    if not conta_norm:
        return None
    if conta_norm in por_conta:
        return conta_norm
    sem_sufixo_atual = _strip_legal_suffix(conta_norm)
    if sem_sufixo_atual in indice_sem_sufixo:
        return indice_sem_sufixo[sem_sufixo_atual]
    matches = difflib.get_close_matches(
        conta_norm, contas_nomeadas_norms, n=1, cutoff=_LIMIAR_CONTA)
    return matches[0] if matches else None


def match_account_name(nome, catalogo_por_norm):
    """Casa o nome de uma conta citada na ata com um catálogo de contas do
    CRM (`{nome_normalizado: id}`), reaproveitando o mesmo casamento em três
    passos usado para achar a conta na ata anterior
    (`_match_previous_account_key`): nome exato -> nome sem sufixo de forma
    jurídica ("Ambev" == "Ambev S.A.") -> similaridade (cutoff conservador,
    ver `_LIMIAR_CONTA`).

    Devolve `(account_id, confidence)`, ou `(None, None)` se não houver
    catálogo, nome, ou nenhum candidato. `confidence` é 'alta' para os dois
    primeiros passos (determinísticos) e 'media' para o fuzzy match.
    """
    norm = normalize_name(nome)
    if not norm or not catalogo_por_norm:
        return None, None
    nomes = list(catalogo_por_norm.keys())
    indice_sem_sufixo = {}
    for k in nomes:
        indice_sem_sufixo.setdefault(_strip_legal_suffix(k), k)
    chave = _match_previous_account_key(norm, catalogo_por_norm, nomes, indice_sem_sufixo)
    if chave is None:
        return None, None
    # Determinístico (exato ou só diferindo por sufixo de forma jurídica) ->
    # 'alta'; qualquer outra coisa só pode ter vindo do passo fuzzy -> 'media'.
    deterministico = chave == norm or _strip_legal_suffix(chave) == _strip_legal_suffix(norm)
    return catalogo_por_norm[chave], ('alta' if deterministico else 'media')


def _status_efetivo(opp):
    """O último status REAL de uma oportunidade anterior, para propagar como
    `previous_status` na ata nova.

    Achado da revisão final (C1): quando uma oportunidade é pulada por duas
    (ou mais) atas seguidas, `_anexar_nao_citados` grava `update_text =
    SEM_UPDATE` na ata do meio para marcar "não foi citada aqui" — mas esse
    `SEM_UPDATE` NÃO é status, é ausência de status. Se a próxima reconciliação
    lê `update_text` cegamente como "o status anterior", o texto real do
    negócio (ex.: "Proposta enviada em 10/01") é substituído por "Sem update
    nesta reunião" e desaparece da cadeia para sempre — a ata errada renderiza
    duas linhas sem informação nenhuma ("Sem update" seguido de "Update: Sem
    update"), exatamente o oposto da promessa de continuidade da feature.

    A regra: se `update_text` é um status real (não vazio, não SEM_UPDATE),
    ele é o efetivo. Senão, o status real é o `previous_status` que a ata
    anterior já vinha carregando (o carry-over também propaga esse campo —
    ver `_anexar_nao_citados` — então ele nunca se perde, só se um
    `update_text` real aparecer entre o meio, que é quando esta função pega o
    caminho feliz acima)."""
    texto = (opp.get('update_text') or '').strip()
    if texto and texto != SEM_UPDATE:
        return texto
    return (opp.get('previous_status') or '').strip() or None


def reconcile(current_managers, previous_managers, resolver=None):
    """Casa a hierarquia extraída da reunião nova com a da ata anterior.

    - match exato por nome normalizado (conta + oportunidade) -> carrega
      status, `match_confidence='alta'`;
    - nenhum candidato -> oportunidade nova;
    - mais de um candidato parecido -> delega ao `resolver`, chamado UMA vez
      com a lista de pares ambíguos; sem resolver (ou sem decisão para um
      par), vira nova com confiança 'baixa';
    - o que estava na anterior e não apareceu -> entra com `carried_over` e
      `update_text = SEM_UPDATE`, na mesma conta/gerente que foi casada
      (ou recriando o bloco, se a conta inteira sumiu da reunião nova).

    `resolver(pares) -> {indice_do_par: id_da_oportunidade_anterior | None}`.
    Índices podem vir como string (ex.: de um JSON parseado) — são
    normalizados para `int`. `None` (ou índice ausente do retorno) significa
    "sem decisão", não "casou com uma oportunidade sem id" (I3). Se o
    resolver devolver o mesmo id para dois pares diferentes, só o primeiro é
    aceito — o segundo vira 'baixa' (I4). Uma exceção do resolver é
    registrada via `logging` e tratada como "sem decisão para nenhum par",
    nunca propagada (I6). Um match confirmado pelo resolver recebe
    `match_confidence='media'` — diferente do match exato ('alta'), é
    julgamento de um LLM sobre nomes que não bateram sozinhos.

    `account_id`/`match_confidence`/`match_confirmed` da conta também são
    herdados da conta anterior casada, quando a conta atual não trouxer os
    seus próprios (o que hoje só acontece com `match_confirmed`, já que
    `parsed['managers']`, recém-saído da extração da IA, nunca tem essa
    chave). Um vínculo confirmado pelo usuário (Task 8, rota `/link`) é
    decisão humana — precisa sobreviver ata após ata até alguém desfazê-lo,
    não pode ser apagado em silêncio só porque uma nova ata foi gerada.
    """
    por_opp, por_conta = _index_anterior(previous_managers)
    contas_nomeadas_norms = [
        k for k in por_conta if not k.startswith(_SYNTHETIC_ACCOUNT_PREFIX)]
    # Índice auxiliar para o passo (b) do casamento de conta: nome sem
    # sufixo de forma jurídica -> chave original em por_conta. Primeira
    # ocorrência vence em caso de colisão (duas contas anteriores distintas
    # que colapsam para o mesmo nome sem sufixo é um cenário raro demais
    # para justificar mais mecanismo aqui).
    indice_sem_sufixo = {}
    for k in contas_nomeadas_norms:
        indice_sem_sufixo.setdefault(_strip_legal_suffix(k), k)

    usados_idx = set()
    ids_reivindicados = set()
    pendentes_ambiguos = []  # (opp_saida, candidatos)
    matched_accounts = {}  # conta_key anterior -> dict de saída já criado
    resultado = []

    for manager in (current_managers or []):
        gerente = (manager.get('name') or '').strip() or GERENTE_NAO_IDENTIFICADO
        contas_saida = []
        for account in (manager.get('accounts') or []):
            conta_norm = normalize_name(account.get('name'))
            conta_key = _match_previous_account_key(
                conta_norm, por_conta, contas_nomeadas_norms, indice_sem_sufixo)
            anterior_conta = por_conta.get(conta_key) if conta_key else None

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
                itens_candidatos = por_opp.get((conta_key, normalize_name(nome)), []) if conta_key else []
                exato = next((it for it in itens_candidatos if it['idx'] not in usados_idx), None)
                if exato is not None:
                    usados_idx.add(exato['idx'])
                    # C1: propaga o último status REAL, não um SEM_UPDATE
                    # carregado de uma ata em que esta oportunidade foi pulada
                    # — ver `_status_efetivo`.
                    saida['previous_status'] = _status_efetivo(exato['data'])
                    saida['prev_opportunity_id'] = exato['data'].get('id')
                    saida['match_confidence'] = 'alta'
                else:
                    disponiveis = [
                        it for it in (anterior_conta['opportunities'] if anterior_conta else [])
                        if it['idx'] not in usados_idx
                    ]
                    candidatos = _candidatos_proximos(nome, disponiveis)
                    if candidatos:
                        pendentes_ambiguos.append((saida, candidatos))
                opps_saida.append(saida)

            # Um vínculo confirmado pelo usuário (Task 8, rota /link) é
            # decisão humana — tem precedência sobre o que veio da extração
            # nova (que nunca traz match_confirmed: parsed['managers'] é
            # fresco da IA). Só herda de anterior_conta quando a conta atual
            # não trouxer confirmação própria (o que hoje nunca acontece
            # aqui, mas não custa não presumir).
            confirmado_anterior = bool(anterior_conta and anterior_conta.get('match_confirmed'))
            conta_saida = {
                'name': (account.get('name') or '').strip(),
                'account_id': account.get('account_id') or (anterior_conta.get('account_id') if anterior_conta else None),
                'match_confidence': account.get('match_confidence') or (
                    anterior_conta.get('match_confidence') if confirmado_anterior else None),
                'match_confirmed': bool(account.get('match_confirmed')) or confirmado_anterior,
                'opportunities': opps_saida,
            }
            contas_saida.append(conta_saida)
            if conta_key:
                matched_accounts.setdefault(conta_key, conta_saida)
        resultado.append({'name': gerente, 'accounts': contas_saida})

    _resolver_ambiguos(pendentes_ambiguos, resolver, usados_idx, ids_reivindicados)
    _anexar_nao_citados(resultado, por_conta, usados_idx, matched_accounts)
    return resultado


def _candidatos_proximos(nome, itens_anteriores):
    alvo = normalize_name(nome)
    if not alvo:
        return []
    achados = []
    for it in itens_anteriores:
        ratio = difflib.SequenceMatcher(None, alvo, normalize_name(it['data'].get('name'))).ratio()
        if ratio >= _LIMIAR_AMBIGUIDADE:
            achados.append(it)
    return achados


def _resolver_ambiguos(pendentes, resolver, usados_idx, ids_reivindicados):
    if not pendentes:
        return
    if resolver is None:
        for saida, _itens in pendentes:
            saida['match_confidence'] = 'baixa'
        return

    pares = [
        {'index': i, 'nome_novo': saida['name'],
         'candidatos': [{'id': it['data'].get('id'), 'nome': it['data'].get('name')} for it in itens]}
        for i, (saida, itens) in enumerate(pendentes)
    ]
    try:
        decisoes = resolver(pares) or {}
    except Exception:
        # I6: uma queda do resolver (ex.: chamada de LLM) não pode ficar
        # indistinguível de "não havia match" — registra o rastro e segue
        # tratando todos os pares como sem decisão.
        _logger.warning('resolver de reconciliação do iAta falhou; tratando '
                         'pares ambíguos como novos', exc_info=True)
        decisoes = {}

    # I5: um resolver que parseia JSON devolve chaves string ("0"); sem essa
    # normalização todos os pares cairiam em "sem decisão" silenciosamente.
    decisoes_norm = {}
    for k, v in decisoes.items():
        try:
            decisoes_norm[int(k)] = v
        except (TypeError, ValueError):
            continue

    for i, (saida, itens) in enumerate(pendentes):
        # I3: índice ausente ou valor None é "não decidi" — não deve ser
        # tratado como "decidi casar com um candidato sem id".
        if i not in decisoes_norm or decisoes_norm[i] is None:
            saida['match_confidence'] = 'baixa'
            continue
        escolhido = decisoes_norm[i]
        # I4: o mesmo id não pode ser reivindicado por dois pares — o
        # segundo a chegar vira 'baixa' em vez de duplicar o carregamento.
        if escolhido in ids_reivindicados:
            saida['match_confidence'] = 'baixa'
            continue
        item = next((it for it in itens
                     if it['data'].get('id') == escolhido and it['idx'] not in usados_idx), None)
        if item is None:
            saida['match_confidence'] = 'baixa'
            continue
        usados_idx.add(item['idx'])
        ids_reivindicados.add(escolhido)
        saida['prev_opportunity_id'] = item['data'].get('id')
        # C1: mesma correção do ramo de match exato — ver `_status_efetivo`.
        saida['previous_status'] = _status_efetivo(item['data'])
        # 'media', não 'alta': é julgamento de um LLM sobre nomes que não
        # bateram sozinhos, diferente do match exato/determinístico acima.
        saida['match_confidence'] = 'media'


def _anexar_nao_citados(resultado, por_conta, usados_idx, matched_accounts):
    """Tudo que estava na ata anterior e não apareceu na reunião nova entra
    como carried_over — garantido por código, não pelo modelo."""
    # I1: gerentes são casados por nome normalizado, não por string exata —
    # "ANA PAULA" e "Ana Paula" são a mesma pessoa. Duas pessoas distintas
    # que por acaso normalizam para o mesmo nome colapsam no mesmo bloco;
    # essa é uma decisão deliberada (o dado de entrada não nos dá como
    # diferenciá-las de outra forma), não um efeito colateral de dict.
    por_gerente = {}
    for m in resultado:
        por_gerente.setdefault(normalize_name(m['name']), m)

    for conta_key, dados in por_conta.items():
        faltantes = [it for it in dados['opportunities'] if it['idx'] not in usados_idx]
        if not faltantes:
            continue

        destino = matched_accounts.get(conta_key)
        if destino is None:
            gerente_norm = normalize_name(dados['manager'])
            gerente = por_gerente.get(gerente_norm)
            if gerente is None:
                gerente = {'name': dados['manager'], 'accounts': []}
                por_gerente[gerente_norm] = gerente
                resultado.append(gerente)
            destino = {
                'name': dados['name'],
                'account_id': dados.get('account_id'),
                'match_confidence': dados.get('match_confidence') if dados.get('match_confirmed') else None,
                'match_confirmed': bool(dados.get('match_confirmed')),
                'opportunities': [],
            }
            gerente['accounts'].append(destino)
            matched_accounts[conta_key] = destino

        for it in faltantes:
            opp = it['data']
            destino['opportunities'].append({
                'name': (opp.get('name') or '').strip(),
                'update_text': SEM_UPDATE,
                'responsible': (opp.get('responsible') or '').strip() or dados['manager'],
                # C1: propaga o último status REAL da oportunidade, não um
                # SEM_UPDATE herdado de uma ata anterior em que ela também
                # foi pulada — ver `_status_efetivo`. Sem isto, duas atas
                # seguidas sem citar a oportunidade apagavam o último status
                # real da cadeia para sempre.
                'previous_status': _status_efetivo(opp),
                'carried_over': True,
                'prev_opportunity_id': opp.get('id'),
                'match_confidence': None,
            })
