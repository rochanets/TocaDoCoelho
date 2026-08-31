# -*- coding: utf-8 -*-
# Rotas do submódulo "Capacitação" do WikiToca (sessões, mensagens, documentos
# de treino e chamadas de LLM com barra de progresso).
# Este arquivo é executado no namespace de app.py por _load_route_modules(),
# depois de routes/wikitoca.py: tem acesso a todos os helpers/globals de
# app.py (incluindo `_wiki_norm`, definida lá) e registra as rotas no mesmo
# objeto Flask `app`, com URLs idênticas às originais.

# Palavras curtas e conectivos não distinguem trecho relevante de irrelevante.
_WIKI_STOPWORDS = {
    'a', 'ao', 'aos', 'as', 'com', 'como', 'da', 'das', 'de', 'do', 'dos', 'e', 'em',
    'na', 'nas', 'no', 'nos', 'o', 'os', 'ou', 'para', 'pela', 'pelo', 'por', 'qual',
    'quais', 'que', 'quem', 'se', 'sobre', 'um', 'uma', 'the', 'of', 'and', 'to',
}

WIKI_CHUNK_SIZE = 1200
WIKI_CHUNK_OVERLAP = 150
WIKI_MIN_CHUNK_SCORE = 1.0


def _wiki_tokens(texto):
    """Termos significativos de um texto, normalizados.

    `_wiki_norm` (definida em routes/wikitoca.py, disponível aqui pelo namespace
    compartilhado) já derruba acento, caixa e caracteres de formatação, então o
    split por `[^a-z0-9]+` basta.
    """
    brutos = re.split(r'[^a-z0-9]+', _wiki_norm(texto))
    return [t for t in brutos if len(t) >= 3 and t not in _WIKI_STOPWORDS]


def _wiki_split_chunks(texto):
    """Quebra o texto em blocos com sobreposição, para não cortar uma frase ao meio."""
    texto = (texto or '').strip()
    if not texto:
        return []
    if len(texto) <= WIKI_CHUNK_SIZE:
        return [texto]
    blocos = []
    passo = WIKI_CHUNK_SIZE - WIKI_CHUNK_OVERLAP
    for ini in range(0, len(texto), passo):
        bloco = texto[ini:ini + WIKI_CHUNK_SIZE].strip()
        if bloco:
            blocos.append(bloco)
    return blocos


def _wiki_rank_chunks(sources, question, top_n=6, min_score=WIKI_MIN_CHUNK_SCORE):
    """Seleciona os trechos mais relevantes para a pergunta.

    `sources` é uma lista de {'label': str, 'text': str}. Cada termo distinto da
    pergunta presente no bloco vale 1 ponto, mais um bônus pela raridade do termo
    no conjunto (um termo presente em quase todo bloco distingue pouco). O piso
    de 1 ponto por termo é o que faz `min_score=1.0` significar "casou pelo menos
    um termo significativo": só com o bônus de raridade, um conjunto de poucos
    blocos daria pontuação abaixo de 1 mesmo para o bloco certo.

    Devolve [{'label', 'chunk', 'score'}] ordenado, ou [] se nenhum bloco atingir
    `min_score` — o chamador usa isso para pular o passo da cascata sem gastar
    chamada de LLM.
    """
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

    import math
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
    return pontuados[:top_n]
