"""Smoke das rotas de runtime contra PostgreSQL (Fase 2 — sub-PR 2c).

Exercita um conjunto representativo de rotas pelo test client do Flask, contra o
backend Postgres, garantindo que a tradução SQLite→PG no wrapper de conexão faz
as queries de runtime rodarem (nenhuma retorna 5xx). Roda só no CI com serviço
Postgres; é pulado localmente sem DATABASE_URL Postgres.
"""
import os

import pytest

import app as toca

_URL = os.getenv('DATABASE_URL', '')
pytestmark = pytest.mark.skipif(
    not _URL.startswith(('postgres://', 'postgresql://')),
    reason='DATABASE_URL PostgreSQL ausente (roda só no CI com serviço Postgres)',
)

GET_ROUTES = [
    '/healthz',
    '/api/clientes', '/api/accounts', '/api/campaigns', '/api/agenda',
    '/api/kanban/columns', '/api/kanban/cards', '/api/config/profile',
    '/api/config/templates', '/api/config/status',
    '/api/autotoca/mala-direta/positions', '/api/autotoca/mala-direta/areas',
    '/api/autotoca/accounts', '/api/environment/cards', '/api/environment/responses',
    '/api/home/overview', '/api/home/drilldown', '/api/home/cobertura-detail',
    '/api/inbound/pending', '/api/inbound/metrics', '/api/commitments/alerts',
    '/api/cargos', '/api/empresas', '/api/activities', '/api/itoca/history',
    '/api/account-planning/runs',
]


@pytest.fixture(scope='module')
def client():
    toca.app.config['TESTING'] = True
    with toca.app.test_client() as c:
        yield c


@pytest.mark.parametrize('url', GET_ROUTES)
def test_get_route_no_server_error(client, url):
    r = client.get(url)
    assert r.status_code < 500, \
        f'{url} -> {r.status_code}: {r.get_data(as_text=True)[:200]}'


def test_create_client_returns_id(client):
    # Exercita INSERT + lastrowid (via RETURNING id no wrapper).
    r = client.post('/api/clientes', data={
        'name': 'PG Route Test', 'company': 'Empresa', 'position': 'Gerente'})
    assert r.status_code == 201, r.get_data(as_text=True)
    assert r.get_json().get('id'), 'INSERT não devolveu id (lastrowid)'


def test_client_search_like(client):
    # Exercita LIKE com parâmetro (escape de '%' literal com params).
    r = client.get('/api/clientes?search=PG')
    assert r.status_code < 500, r.get_data(as_text=True)[:200]
