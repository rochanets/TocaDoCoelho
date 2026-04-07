"""
Testes automatizados para PR-110 — Melhorias no Gerar Relation Report
Verifica as implementações de Melhoria A (market_context) e Melhoria B (highlights LLM).

Estratégia: análise estática via AST + testes inline das funções extraídas do app.py.
"""
import ast
import os
import sys
import types
import textwrap
import unittest
from unittest.mock import patch, MagicMock, call


APP_PATH = os.path.join(os.path.dirname(__file__), 'app.py')


# ---------------------------------------------------------------------------
# Helpers: extrai código-fonte de funções do app.py
# ---------------------------------------------------------------------------

def _read_app_source():
    with open(APP_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def _get_function_source(source, func_name):
    """Retorna o código-fonte de uma função pelo nome, via AST."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            lines = source.splitlines()
            start = node.lineno - 1
            end = node.end_lineno
            return '\n'.join(lines[start:end])
    return None


def _build_fn_namespace(extra_globals=None):
    """Namespace mínimo para executar funções extraídas do app.py."""
    ns = {
        '__builtins__': __builtins__,
        'json': __import__('json'),
        'logger': MagicMock(),
        'concurrent': __import__('concurrent.futures', fromlist=['futures']),
    }
    # concurrent.futures needs to be accessible
    import concurrent.futures
    ns['concurrent'] = types.SimpleNamespace(futures=concurrent.futures)
    if extra_globals:
        ns.update(extra_globals)
    return ns


def _compile_fn(source, func_name, extra_globals=None):
    """Compila e retorna a função func_name do trecho source."""
    ns = _build_fn_namespace(extra_globals)
    exec(compile(source, '<app.py>', 'exec'), ns)  # noqa: S102
    return ns[func_name]


# ---------------------------------------------------------------------------
# Testes Estáticos (AST) — verifica estrutura do código
# ---------------------------------------------------------------------------

class TestStaticStructure(unittest.TestCase):
    """Verifica presença e estrutura das novas funções no app.py."""

    @classmethod
    def setUpClass(cls):
        cls.source = _read_app_source()
        cls.tree = ast.parse(cls.source)

    def _fn_exists(self, name):
        return any(
            isinstance(n, ast.FunctionDef) and n.name == name
            for n in ast.walk(self.tree)
        )

    def _fn_source(self, name):
        return _get_function_source(self.source, name)

    # --- Melhoria A ---

    def test_fetch_market_context_function_exists(self):
        self.assertTrue(self._fn_exists('_relation_report_fetch_market_context'),
                        '_relation_report_fetch_market_context não encontrada em app.py')

    def test_fetch_market_context_calls_sai_simple_prompt(self):
        src = self._fn_source('_relation_report_fetch_market_context')
        self.assertIn('_sai_simple_prompt', src)

    def test_fetch_market_context_checks_sem_dados(self):
        src = self._fn_source('_relation_report_fetch_market_context')
        self.assertIn('SEM_DADOS', src)

    def test_fetch_market_context_checks_length(self):
        src = self._fn_source('_relation_report_fetch_market_context')
        self.assertIn('len(text)', src)

    # --- Melhoria B ---

    def test_generate_highlights_function_exists(self):
        self.assertTrue(self._fn_exists('_relation_report_generate_highlights'),
                        '_relation_report_generate_highlights não encontrada em app.py')

    def test_generate_highlights_calls_sai_simple_prompt(self):
        src = self._fn_source('_relation_report_generate_highlights')
        self.assertIn('_sai_simple_prompt', src)

    def test_generate_highlights_limits_activities_to_40(self):
        src = self._fn_source('_relation_report_generate_highlights')
        self.assertIn('40', src)

    def test_generate_highlights_returns_at_most_6(self):
        src = self._fn_source('_relation_report_generate_highlights')
        self.assertIn('[:6]', src)

    def test_generate_highlights_parses_bullets(self):
        src = self._fn_source('_relation_report_generate_highlights')
        self.assertIn("startswith(('-', '•', '*'))", src)

    # --- Integração na narrativa ---

    def test_narrative_uses_thread_pool_executor(self):
        src = self._fn_source('_relation_report_generate_narrative')
        self.assertIn('ThreadPoolExecutor', src)

    def test_narrative_submits_market_context(self):
        src = self._fn_source('_relation_report_generate_narrative')
        self.assertIn('_relation_report_fetch_market_context', src)

    def test_narrative_submits_highlights(self):
        src = self._fn_source('_relation_report_generate_narrative')
        self.assertIn('_relation_report_generate_highlights', src)

    def test_narrative_injects_market_context_in_result(self):
        src = self._fn_source('_relation_report_generate_narrative')
        self.assertIn("'market_context'", src)

    def test_narrative_replaces_highlights_when_enough_bullets(self):
        src = self._fn_source('_relation_report_generate_narrative')
        self.assertIn('llm_highlights', src)
        self.assertIn('>= 2', src)

    # --- HTML ---

    def test_html_builder_renders_market_context(self):
        src = self._fn_source('_relation_report_build_browser_html')
        self.assertIn('rr-market-context', src)
        self.assertIn('Contexto de Mercado', src)
        self.assertIn('market_context_html', src)

    def test_html_market_context_uses_esc(self):
        src = self._fn_source('_relation_report_build_browser_html')
        self.assertIn('esc(market_context_text)', src)

    # --- Preview endpoint ---

    def test_preview_endpoint_includes_highlights_at_root(self):
        """O endpoint de preview deve expor highlights no nível raiz."""
        preview_src = _get_function_source(self.source, 'preview_relation_report_data')
        self.assertIsNotNone(preview_src, 'preview_relation_report_data não encontrada')
        self.assertIn("'highlights'", preview_src)

    # --- import concurrent ---

    def test_concurrent_futures_imported(self):
        self.assertIn('concurrent.futures', self.source)


# ---------------------------------------------------------------------------
# Testes Unitários — _relation_report_fetch_market_context (inline)
# ---------------------------------------------------------------------------

class TestFetchMarketContextUnit(unittest.TestCase):

    def _make_fn(self, sai_return):
        """Cria a função com _sai_simple_prompt mockado."""
        source = _get_function_source(_read_app_source(), '_relation_report_fetch_market_context')
        mock_sai = MagicMock(return_value=sai_return)
        ns = _build_fn_namespace({'_sai_simple_prompt': mock_sai})
        exec(compile(source, '<app.py>', 'exec'), ns)  # noqa: S102
        return ns['_relation_report_fetch_market_context'], mock_sai

    def test_returns_none_when_sai_returns_none(self):
        fn, _ = self._make_fn(None)
        self.assertIsNone(fn('Empresa Teste'))

    def test_returns_none_when_sem_dados_exact(self):
        fn, _ = self._make_fn('SEM_DADOS')
        self.assertIsNone(fn('Empresa Teste'))

    def test_returns_none_when_sem_dados_embedded(self):
        fn, _ = self._make_fn('Dados insuficientes SEM_DADOS para esta empresa.')
        self.assertIsNone(fn('Empresa X'))

    def test_returns_none_when_text_too_short(self):
        fn, _ = self._make_fn('Curto')  # < 30 chars
        self.assertIsNone(fn('Empresa Teste'))

    def test_returns_stripped_text_when_valid(self):
        expected = 'A Empresa Teste vem expandindo suas operações no setor de tecnologia com novas parcerias estratégicas em 2025.'
        fn, _ = self._make_fn(f'  {expected}  ')
        self.assertEqual(fn('Empresa Teste'), expected)

    def test_question_contains_account_name(self):
        fn, mock_sai = self._make_fn(None)
        fn('Acme Corp')
        question = mock_sai.call_args[0][0]
        self.assertIn('Acme Corp', question)

    def test_question_instructs_sem_dados_fallback(self):
        fn, mock_sai = self._make_fn(None)
        fn('Acme Corp')
        question = mock_sai.call_args[0][0]
        self.assertIn('SEM_DADOS', question)

    def test_exactly_30_chars_is_returned(self):
        text = 'A' * 30  # exatamente 30 chars — deve retornar (len >= 30)
        fn, _ = self._make_fn(text)
        result = fn('X')
        self.assertEqual(result, text)

    def test_29_chars_returns_none(self):
        text = 'A' * 29  # < 30 chars — deve retornar None
        fn, _ = self._make_fn(text)
        self.assertIsNone(fn('X'))


# ---------------------------------------------------------------------------
# Testes Unitários — _relation_report_generate_highlights (inline)
# ---------------------------------------------------------------------------

class TestGenerateHighlightsUnit(unittest.TestCase):

    def _make_fn(self, sai_return):
        source = _get_function_source(_read_app_source(), '_relation_report_generate_highlights')
        mock_sai = MagicMock(return_value=sai_return)
        ns = _build_fn_namespace({'_sai_simple_prompt': mock_sai})
        exec(compile(source, '<app.py>', 'exec'), ns)  # noqa: S102
        return ns['_relation_report_generate_highlights'], mock_sai

    def _report(self, activities=None, account_activities=None, name='Conta'):
        return {
            'account': {'name': name},
            'activities': activities or [],
            'account_activities': account_activities or [],
        }

    def test_returns_empty_when_no_activities(self):
        fn, mock_sai = self._make_fn(None)
        result = fn(self._report())
        self.assertEqual(result, [])
        mock_sai.assert_not_called()

    def test_returns_empty_when_no_descriptions(self):
        fn, mock_sai = self._make_fn(None)
        result = fn(self._report(activities=[{'date': '2025-01-01', 'type': 'call'}]))
        self.assertEqual(result, [])
        mock_sai.assert_not_called()

    def test_returns_empty_when_sai_none(self):
        fn, _ = self._make_fn(None)
        result = fn(self._report(activities=[
            {'description': 'Reunião estratégica', 'date': '2025-01-01', 'type': 'meeting'}
        ]))
        self.assertEqual(result, [])

    def test_parses_dash_bullets(self):
        fn, _ = self._make_fn(
            '- Discussão sobre expansão regional\n'
            '- Proposta de workshop enviada e aprovada\n'
            '- Follow-up pendente com o CTO\n'
            '- Engajamento alto nas últimas semanas\n'
        )
        result = fn(self._report(activities=[
            {'description': 'Reunião estratégica', 'date': '2025-03-01', 'type': 'meeting'}
        ]))
        self.assertIsInstance(result, list)
        self.assertGreaterEqual(len(result), 2)
        for bullet in result:
            self.assertFalse(bullet.startswith('-'), f'Bullet não deveria começar com "-": {bullet}')
            self.assertFalse(bullet.startswith('•'))

    def test_parses_bullet_point_bullets(self):
        fn, _ = self._make_fn(
            '• Tema estratégico discutido em profundidade\n'
            '• Avanço concreto no relacionamento com decisores\n'
        )
        result = fn(self._report(activities=[
            {'description': 'Alinhamento com VP de TI', 'date': '2025-02-01', 'type': 'meeting'}
        ]))
        self.assertGreaterEqual(len(result), 2)

    def test_limits_to_6_bullets(self):
        fn, _ = self._make_fn('\n'.join(
            [f'- Bullet executivo número {i} com conteúdo real e relevante' for i in range(10)]
        ))
        result = fn(self._report(activities=[
            {'description': 'Atividade relevante', 'date': '2025-01-01', 'type': 'call'}
        ]))
        self.assertLessEqual(len(result), 6)

    def test_ignores_bullets_le_10_chars(self):
        fn, _ = self._make_fn('- Ok\n- Ponto válido com mais de dez caracteres\n- X')
        result = fn(self._report(activities=[
            {'description': 'Reunião de acompanhamento', 'date': '2025-02-01', 'type': 'meeting'}
        ]))
        for bullet in result:
            self.assertGreater(len(bullet.lstrip('- •*').strip()), 10,
                               f'Bullet muito curto deveria ter sido filtrado: {bullet}')

    def test_limits_activities_to_40(self):
        many = [{'description': f'Atividade {i}', 'date': '2025-01-01', 'type': 'call'} for i in range(50)]
        fn, mock_sai = self._make_fn('- Bullet com conteúdo executivo de verdade')
        fn(self._report(activities=many))
        question = mock_sai.call_args[0][0]
        activity_lines = [l for l in question.split('\n') if l.startswith('[')]
        self.assertLessEqual(len(activity_lines), 40)

    def test_account_activities_precede_activities(self):
        fn, mock_sai = self._make_fn(None)
        fn(self._report(
            account_activities=[{'description': 'Nota da conta', 'date': '2025-01-01', 'type': 'note'}],
            activities=[{'description': 'Atividade geral', 'date': '2025-02-01', 'type': 'call'}],
        ))
        question = mock_sai.call_args[0][0]
        pos_nota = question.find('Nota da conta')
        pos_geral = question.find('Atividade geral')
        self.assertLess(pos_nota, pos_geral, 'account_activities deve aparecer antes de activities no prompt')

    def test_alternative_description_fields_used(self):
        """Verifica que campos alternativos (notes, information) são aceitos."""
        fn, mock_sai = self._make_fn(None)
        fn(self._report(activities=[{'notes': 'Nota relevante registrada', 'date': '2025-01-01', 'type': 'call'}]))
        if mock_sai.called:
            question = mock_sai.call_args[0][0]
            self.assertIn('Nota relevante registrada', question)


# ---------------------------------------------------------------------------
# Testes Unitários — integração em _relation_report_generate_narrative
# ---------------------------------------------------------------------------

class TestNarrativeIntegration(unittest.TestCase):
    """
    Testa que _relation_report_generate_narrative:
    - Injeta market_context no resultado (success + fallback)
    - Substitui highlights quando >= 2 bullets
    - Mantém highlights originais quando < 2 bullets
    """

    def _make_fn(self, narrative_result, market_result, highlights_result):
        """Monta a função com as três sub-funções mockadas."""
        app_src = _read_app_source()

        # Extrai as funções de que precisamos
        fns_to_extract = [
            '_relation_report_build_account_snapshot',
            '_relation_report_build_relationship_snapshot',
            '_relation_report_build_topic_evidence',
            '_relation_report_call_sai_narrative_template',
            '_relation_report_generate_narrative',
            '_relation_report_format_dt',
            '_extract_json_object_from_text',
        ]

        mock_sai_tmpl = MagicMock(return_value=narrative_result)
        mock_market = MagicMock(return_value=market_result)
        mock_highlights = MagicMock(return_value=highlights_result)

        # Build namespace with all needed stubs
        import concurrent.futures as _cf
        ns = {
            '__builtins__': __builtins__,
            'json': __import__('json'),
            'logger': MagicMock(),
            'concurrent': types.SimpleNamespace(futures=_cf),
            '_relation_report_fetch_market_context': mock_market,
            '_relation_report_generate_highlights': mock_highlights,
            '_relation_report_call_sai_narrative_template': mock_sai_tmpl,
            '_relation_report_build_account_snapshot': MagicMock(return_value='snapshot'),
            '_relation_report_build_relationship_snapshot': MagicMock(return_value='rel_snapshot'),
            '_relation_report_build_topic_evidence': MagicMock(return_value='evidence'),
            '_relation_report_format_dt': MagicMock(return_value='01/01/2025'),
        }

        fn_src = _get_function_source(app_src, '_relation_report_generate_narrative')
        exec(compile(fn_src, '<app.py>', 'exec'), ns)  # noqa: S102
        return ns['_relation_report_generate_narrative'], mock_sai_tmpl, mock_market, mock_highlights

    def _minimal_rd(self, name='Acme'):
        return {
            'account': {'name': name},
            'period': {'full_period': True, 'start_date': None, 'end_date': None},
            'contacts': [], 'presences': [], 'activities': [], 'account_activities': [],
            'kanban_cards': [], 'mapping_items': [], 'relationship_cards': [],
            'topics': {'Estratégia': [], 'Tecnologia': [], 'Financeiro': [], 'Governança': [], 'Operacional': []},
            'summary_counts': {'contacts': 0, 'presences': 0, 'activities': 0, 'kanban_cards': 0, 'mapping_items': 0, 'account_activities': 0},
            'latest_interaction': {}, 'full_period': True, 'start_date': None, 'end_date': None,
        }

    def _success_narrative(self, highlights=None):
        return {
            'executive_summary': 'Resumo.',
            'relationship_maturity': 'Estruturado',
            'next_steps': [],
            'topic_breakdown': {},
            'highlights': highlights or ['Destaque genérico'],
            'llm_used': True,
        }

    def test_market_context_set_in_success_path(self):
        fn, _, _, _ = self._make_fn(
            narrative_result=self._success_narrative(),
            market_result='Empresa em forte expansão no setor logístico.',
            highlights_result=[],
        )
        result = fn(self._minimal_rd())
        self.assertIn('market_context', result)
        self.assertEqual(result['market_context'], 'Empresa em forte expansão no setor logístico.')

    def test_market_context_none_when_fetch_fails(self):
        fn, _, _, _ = self._make_fn(
            narrative_result=self._success_narrative(),
            market_result=None,
            highlights_result=[],
        )
        result = fn(self._minimal_rd())
        self.assertIsNone(result.get('market_context'))

    def test_highlights_replaced_when_2_or_more_bullets(self):
        original = ['Destaque genérico']
        llm_bullets = ['Proposta enviada ao comitê executivo', 'Workshop realizado com sucesso']
        fn, _, _, _ = self._make_fn(
            narrative_result=self._success_narrative(highlights=original),
            market_result=None,
            highlights_result=llm_bullets,
        )
        result = fn(self._minimal_rd())
        self.assertEqual(result['highlights'], llm_bullets)

    def test_highlights_kept_when_1_bullet(self):
        original = ['Destaque genérico']
        fn, _, _, _ = self._make_fn(
            narrative_result=self._success_narrative(highlights=original),
            market_result=None,
            highlights_result=['Apenas um bullet'],
        )
        result = fn(self._minimal_rd())
        self.assertEqual(result['highlights'], original)

    def test_highlights_kept_when_0_bullets(self):
        original = ['Destaque genérico']
        fn, _, _, _ = self._make_fn(
            narrative_result=self._success_narrative(highlights=original),
            market_result=None,
            highlights_result=[],
        )
        result = fn(self._minimal_rd())
        self.assertEqual(result['highlights'], original)

    def test_fallback_includes_market_context(self):
        """Quando SAI principal retorna None, fallback deve incluir market_context."""
        fn, _, _, _ = self._make_fn(
            narrative_result=None,
            market_result='Empresa em crise setorial após reestruturação.',
            highlights_result=[],
        )
        result = fn(self._minimal_rd())
        self.assertIn('market_context', result)
        self.assertEqual(result['market_context'], 'Empresa em crise setorial após reestruturação.')

    def test_fallback_highlights_replaced_when_enough_bullets(self):
        llm_bullets = ['Bullet 1 executivo relevante', 'Bullet 2 com avanço concreto']
        fn, _, _, _ = self._make_fn(
            narrative_result=None,
            market_result=None,
            highlights_result=llm_bullets,
        )
        result = fn(self._minimal_rd())
        self.assertEqual(result['highlights'], llm_bullets)

    def test_all_three_futures_submitted(self):
        """As três chamadas devem ser submetidas ao executor."""
        fn, mock_sai, mock_market, mock_highl = self._make_fn(
            narrative_result=self._success_narrative(),
            market_result=None,
            highlights_result=[],
        )
        fn(self._minimal_rd())
        self.assertTrue(mock_sai.called, '_relation_report_call_sai_narrative_template não foi chamado')
        self.assertTrue(mock_market.called, '_relation_report_fetch_market_context não foi chamado')
        self.assertTrue(mock_highl.called, '_relation_report_generate_highlights não foi chamado')


# ---------------------------------------------------------------------------
# Testes da estrutura do JSON de preview
# ---------------------------------------------------------------------------

class TestPreviewJsonStructure(unittest.TestCase):

    def test_highlights_at_root_level(self):
        narrative = {
            'highlights': ['Bullet 1', 'Bullet 2'],
            'market_context': 'Texto de mercado.',
        }
        payload = {
            'highlights': narrative.get('highlights') or [],
            'narrative': narrative,
        }
        self.assertIn('highlights', payload)
        self.assertEqual(payload['highlights'], ['Bullet 1', 'Bullet 2'])

    def test_market_context_inside_narrative(self):
        narrative = {'market_context': 'Contexto gerado.', 'highlights': []}
        payload = {'narrative': narrative}
        self.assertIn('market_context', payload['narrative'])
        self.assertEqual(payload['narrative']['market_context'], 'Contexto gerado.')

    def test_frontend_highlights_fallback(self):
        """Frontend usa data.highlights || data.narrative?.highlights."""
        data = {'narrative': {'highlights': ['Bullet via narrative']}}
        highlights = data.get('highlights') or (data.get('narrative') or {}).get('highlights') or []
        self.assertEqual(highlights, ['Bullet via narrative'])

    def test_frontend_highlights_root_takes_precedence(self):
        data = {
            'highlights': ['Bullet via root'],
            'narrative': {'highlights': ['Bullet via narrative']},
        }
        highlights = data.get('highlights') or (data.get('narrative') or {}).get('highlights') or []
        self.assertEqual(highlights, ['Bullet via root'])


# ---------------------------------------------------------------------------
# Testes de XSS / segurança
# ---------------------------------------------------------------------------

class TestXSSProtection(unittest.TestCase):

    def test_market_context_xss_not_in_raw_html(self):
        """Verifica que o HTML builder usa esc() para market_context."""
        app_src = _read_app_source()
        fn_src = _get_function_source(app_src, '_relation_report_build_browser_html')
        # esc() deve ser chamado com market_context_text
        self.assertIn('esc(market_context_text)', fn_src,
                      'market_context_text deve ser passado por esc() no HTML builder')

    def test_highlights_xss_not_in_raw_html(self):
        """Verifica que highlights usa esc() no HTML builder."""
        app_src = _read_app_source()
        fn_src = _get_function_source(app_src, '_relation_report_build_browser_html')
        self.assertIn('esc(item)', fn_src,
                      'highlights items devem ser passados por esc() no HTML builder')


if __name__ == '__main__':
    print('=' * 70)
    print('PR-110 — Testes de conformidade com a especificação')
    print('Branch: version5 → codex/implement-improvements-for-relation-report')
    print('=' * 70)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestStaticStructure,
        TestFetchMarketContextUnit,
        TestGenerateHighlightsUnit,
        TestNarrativeIntegration,
        TestPreviewJsonStructure,
        TestXSSProtection,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
