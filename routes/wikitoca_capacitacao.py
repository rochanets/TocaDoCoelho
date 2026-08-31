# -*- coding: utf-8 -*-
# Rotas do submódulo "Capacitação" do WikiToca (sessões, mensagens, documentos
# de treino e chamadas de LLM com barra de progresso).
# Este arquivo é executado no namespace de app.py por _load_route_modules(),
# depois de routes/wikitoca.py: tem acesso a todos os helpers/globals de
# app.py (incluindo `_wiki_norm`, definida lá) e registra as rotas no mesmo
# objeto Flask `app`, com URLs idênticas às originais.

import math

# Palavras curtas e conectivos não distinguem trecho relevante de irrelevante.
# Cobre português e inglês: material de capacitação técnico em inglês é
# plausível neste projeto, e sem as function words em inglês o ranking erra
# em acervos pequenos — ex.: "how can you set the retry policy for when a
# request fails" contava how/can/you/for/when como termos de conteúdo e um
# FAQ de ruído vencia o documento que realmente respondia.
_WIKI_STOPWORDS = {
    # Português: artigos, pronomes, preposições, interrogativos, conectivos.
    'a', 'ao', 'aos', 'as', 'com', 'como', 'da', 'das', 'de', 'do', 'dos', 'e', 'em',
    'na', 'nas', 'no', 'nos', 'o', 'os', 'ou', 'para', 'pela', 'pelo', 'por', 'qual',
    'quais', 'que', 'quem', 'se', 'sobre', 'um', 'uma',
    # Inglês: artigos/demonstrativos, pronomes, auxiliares/modais, preposições,
    # interrogativos comuns.
    'the', 'this', 'that', 'these', 'those',
    'you', 'your', 'she', 'her', 'him', 'his', 'its', 'they', 'them', 'their',
    'who', 'whom', 'whose', 'what', 'which',
    'are', 'was', 'were', 'has', 'had', 'have', 'can', 'could', 'will', 'would',
    'should', 'does', 'did', 'been', 'being',
    'for', 'with', 'from', 'into', 'about', 'after', 'before', 'between',
    'during', 'over', 'under', 'without', 'and', 'of', 'to',
    'how', 'when', 'where', 'why',
}

_WIKI_CHUNK_SIZE = 1200
_WIKI_CHUNK_OVERLAP = 150
_WIKI_MIN_CHUNK_SCORE = 1.0


def _wiki_tokens(texto):
    """Termos significativos de um texto, normalizados.

    `_wiki_norm` (definida em routes/wikitoca.py, disponível aqui pelo namespace
    compartilhado) já derruba acento, caixa e caracteres de formatação, então o
    split por `[^a-z0-9]+` basta.
    """
    brutos = re.split(r'[^a-z0-9]+', _wiki_norm(texto))
    return [t for t in brutos if len(t) >= 3 and t not in _WIKI_STOPWORDS]


def _wiki_split_chunks(texto):
    """Quebra o texto em blocos com sobreposição. A sobreposição não evita que
    uma frase seja cortada ao meio (qualquer corte fixo por tamanho pode cair
    no meio de uma frase) — ela garante que frases menores que o tamanho da
    sobreposição sobrevivam íntegras em pelo menos um bloco."""
    texto = (texto or '').strip()
    if not texto:
        return []
    if len(texto) <= _WIKI_CHUNK_SIZE:
        return [texto]
    blocos = []
    passo = _WIKI_CHUNK_SIZE - _WIKI_CHUNK_OVERLAP
    for ini in range(0, len(texto), passo):
        # Sem essa guarda, a última iteração pode gerar uma cauda minúscula
        # (ex.: 38 caracteres) que é puro substring do bloco anterior — o
        # bloco anterior, terminando em ini_anterior + _WIKI_CHUNK_SIZE =
        # ini + _WIKI_CHUNK_OVERLAP, já cobre tudo que sobra quando o restante
        # do texto é <= à sobreposição. `ini and` preserva a primeira janela
        # (ini=0), que sempre deve ser gerada mesmo em texto curto.
        if ini and len(texto) - ini <= _WIKI_CHUNK_OVERLAP:
            break
        bloco = texto[ini:ini + _WIKI_CHUNK_SIZE].strip()
        if bloco:
            blocos.append(bloco)
    return blocos


def _wiki_rank_chunks(sources, question, top_n=6, min_score=_WIKI_MIN_CHUNK_SCORE):
    """Seleciona os trechos mais relevantes para a pergunta.

    `sources` é uma lista de {'label': str, 'text': str}. Cada termo distinto da
    pergunta presente no bloco vale 1 ponto, mais um bônus pela raridade do termo
    no conjunto (um termo presente em quase todo bloco distingue pouco). O piso
    de 1 ponto por termo é o que faz `min_score=1.0` significar "casou pelo menos
    um termo significativo": só com o bônus de raridade, um conjunto de poucos
    blocos daria pontuação abaixo de 1 mesmo para o bloco certo.

    O bônus de raridade (IDF) é calculado só a partir dos blocos desta chamada
    — então scores NÃO são comparáveis entre chamadas com acervos de tamanhos
    diferentes: o mesmo match perfeito vale mais pontos num acervo de milhares
    de blocos do que num acervo de um único bloco. Qualquer limiar absoluto
    introduzido depois (ex.: na cascata) precisa levar isso em conta.

    `top_n` é o número de blocos desejado, não um teto opcional: valores < 1
    são erro de programação do chamador (não "nenhum resultado") e levantam
    ValueError, para não se confundir com o [] que sinaliza "nada relevante".

    Devolve [{'label', 'chunk', 'score'}] ordenado por score decrescente, sem
    conteúdo duplicado (a sobreposição de _wiki_split_chunks pode gerar o
    mesmo texto em blocos diferentes; aqui só o de maior score de cada
    conteúdo distinto entra no resultado), ou [] se nenhum bloco atingir
    `min_score` — o chamador usa isso para pular o passo da cascata sem gastar
    chamada de LLM.
    """
    if top_n < 1:
        raise ValueError(f'top_n deve ser >= 1, recebido {top_n!r}')

    termos = set(_wiki_tokens(question))
    if not termos:
        return []

    blocos = []
    for src in sources or []:
        label = (src.get('label') or 'documento')
        for chunk in _wiki_split_chunks(src.get('text')):
            blocos.append({'label': label, 'chunk': chunk, 'tokens': set(_wiki_tokens(chunk))})
    if not blocos:
        return []

    total = len(blocos)
    freq = {t: sum(1 for b in blocos if t in b['tokens']) for t in termos}

    pontuados = []
    for b in blocos:
        score = 0.0
        for t in termos:
            if t in b['tokens']:
                # 1 ponto por termo casado + bônus de raridade. Os +1 evitam
                # divisão por zero e amortecem termos onipresentes.
                score += 1.0 + math.log(1 + total / (1 + freq[t]))
        if score >= min_score:
            pontuados.append({'label': b['label'], 'chunk': b['chunk'], 'score': round(score, 4)})

    pontuados.sort(key=lambda x: x['score'], reverse=True)

    # Dedup por conteúdo na seleção final, não na geração dos blocos (a
    # sobreposição continua intencional): sem isso, um documento repetitivo
    # pode devolver o mesmo trecho várias vezes e esgotar o orçamento de
    # contexto do LLM em texto duplicado — cenário provável na Task 8, onde o
    # mesmo documento pode chegar por duas fontes (instância + base WikiToca).
    selecionados = []
    vistos = set()
    for p in pontuados:
        if p['chunk'] in vistos:
            continue
        vistos.add(p['chunk'])
        selecionados.append(p)
        if len(selecionados) >= top_n:
            break
    return selecionados
