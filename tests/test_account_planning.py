"""Account Planning: país entra na query Tavily e é persistido na run."""


def test_country_na_query_e_persistido(client, db_path, monkeypatch):
    import app as toca

    # Tavily fake: captura as queries e devolve 1 perfil plausível
    seen_queries = []

    def fake_tavily(api_key, query, max_results=6):
        seen_queries.append(query)
        return [{
            'url': 'https://www.linkedin.com/in/fulano-ceo/',
            'title': 'Fulano Silva - CEO - Empresa Global | LinkedIn',
            'content': 'CEO na Empresa Global, Brasil.',
        }]

    monkeypatch.setattr(toca, '_resolve_setting',
                        lambda k, e=None: 'fake-key' if k == 'tavily_api_key' else '')
    monkeypatch.setattr(toca, '_run_tavily_request', fake_tavily)
    monkeypatch.setattr(toca, '_find_image_candidates_on_web', lambda *a, **k: [])

    # roda o async diretamente (sem thread) para inspecionar o resultado
    task_id = 'tp1'
    toca._bg_task_set(task_id, {'status': 'processing'})
    # a função está no namespace de app via _load_route_modules
    toca._account_planning_search_async(task_id, 'Empresa Global', 'Tecnologia', 'Brasil')

    # país entrou em TODAS as queries montadas
    assert seen_queries, 'nenhuma query foi montada'
    assert all('"Brasil"' in q for q in seen_queries)
    assert all('site:linkedin.com/in' in q for q in seen_queries)

    # país persistido na run e devolvido pelo detail
    runs = client.get('/api/account-planning/runs').get_json()
    assert runs, 'nenhuma run persistida'
    detail = client.get(f"/api/account-planning/runs/{runs[0]['id']}").get_json()
    assert detail['country'] == 'Brasil'
    assert detail['segment'] == 'Tecnologia'
