"""Testes unitários das regras de negócio puras (moeda, status, datas)."""
from datetime import datetime, timedelta

import app as toca


# ---------------------------------------------------------------- moeda

def test_parse_currency_brl():
    assert toca.parse_currency_to_cents('R$ 1.500,00') == 150000
    assert toca.parse_currency_to_cents('R$ 0,99') == 99
    assert toca.parse_currency_to_cents('1500') == 150000
    assert toca.parse_currency_to_cents('') is None
    assert toca.parse_currency_to_cents(None) is None


def test_format_currency_br():
    assert toca.format_currency_br(150000) == 'R$ 1.500,00'
    assert toca.format_currency_br(99) == 'R$ 0,99'
    assert toca.format_currency_br(None) == 'Não informado'


def test_currency_roundtrip():
    for cents in (0, 1, 100, 123456789):
        assert toca.parse_currency_to_cents(toca.format_currency_br(cents)) == cents


# ---------------------------------------------------------------- status semáforo

def test_home_status_for():
    now = datetime(2026, 7, 10, 12, 0, 0)
    fmt = '%Y-%m-%d %H:%M:%S'
    assert toca._home_status_for((now - timedelta(days=2)).strftime(fmt), 7, 14, now)[0] == 'em_dia'
    assert toca._home_status_for((now - timedelta(days=10)).strftime(fmt), 7, 14, now)[0] == 'atencao'
    assert toca._home_status_for((now - timedelta(days=30)).strftime(fmt), 7, 14, now)[0] == 'atrasado'
    # Nunca contatado => atrasado, sem contagem de dias
    assert toca._home_status_for(None, 7, 14, now) == ('atrasado', None)
    # Data só com dia (sem hora) e formato ISO com T também parseiam
    assert toca._home_status_for('2026-07-09', 7, 14, now)[0] == 'em_dia'
    assert toca._home_status_for('2026-07-09T08:30:00', 7, 14, now)[0] == 'em_dia'
    # Data inválida não explode
    assert toca._home_status_for('inválida', 7, 14, now) == ('atrasado', None)


def test_home_status_thresholds_por_cargo(db_path):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("INSERT INTO status_rules (position, green_days, yellow_days) VALUES ('CEO', 3, 5)")
    conn.commit()
    get_thresholds = toca._home_status_thresholds(c)
    assert get_thresholds('CEO') == (3, 5)
    assert get_thresholds('  ceo  ') == (3, 5)          # case/espacos insensível
    assert get_thresholds('Cargo Desconhecido') == (7, 14)  # default universal
    conn.close()


# ---------------------------------------------------------------- datas de atividade

def test_extract_future_commitment_dates():
    dates = toca.extract_future_commitment_dates('Reunião marcada para 25/12/2030 às 15h')
    assert '2030-12-25' in dates
    assert toca.extract_future_commitment_dates('Conversa sem data combinada') == []
