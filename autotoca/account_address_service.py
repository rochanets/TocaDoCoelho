import logging
import re
from typing import Dict, List

import requests


class AccountAddressService:
    def __init__(self, timeout_seconds: int = 12):
        self.timeout_seconds = timeout_seconds
        self.logger = logging.getLogger('toca-do-coelho.autotoca.address')

    @staticmethod
    def _is_candidate_address(text: str) -> bool:
        normalized = (text or '').strip()
        if len(normalized) < 25:
            return False
        has_road = re.search(r'\b(rua|avenida|av\.?|rodovia|alameda|travessa|praça|estrada)\b', normalized, re.IGNORECASE)
        has_number_or_cep = re.search(r'\b\d{1,6}\b|\b\d{5}-?\d{3}\b', normalized)
        return bool(has_road and has_number_or_cep)

    @staticmethod
    def _score_candidate(account_name: str, source: str, snippet: str) -> int:
        text = f'{source} {snippet}'.lower()
        tokens = [t for t in re.split(r'\W+', account_name.lower()) if len(t) > 2]
        token_hits = sum(1 for t in set(tokens) if t in text)
        institutional_bonus = 0
        if any(k in text for k in ['receita', 'cnpj', 'gov.br', 'institucional', 'site oficial', 'matriz', 'sede']):
            institutional_bonus = 4
        address_bonus = 3 if AccountAddressService._is_candidate_address(snippet) else 0
        return token_hits + institutional_bonus + address_bonus

    def _extract_candidates_from_duckduckgo(self, account_name: str) -> List[Dict[str, str]]:
        query = f'"{account_name}" endereço sede matriz CNPJ'
        url = f'https://duckduckgo.com/html/?q={requests.utils.quote(query)}'
        response = requests.get(
            url,
            timeout=self.timeout_seconds,
            headers={'User-Agent': 'Mozilla/5.0 TocaDoCoelho AutoToca'}
        )
        response.raise_for_status()
        html = response.text

        blocks = re.findall(
            r'<a[^>]*class="result__a"[^>]*>(?P<title>.*?)</a>.*?<a[^>]*class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
            html,
            flags=re.IGNORECASE | re.DOTALL
        )

        candidates: List[Dict[str, str]] = []
        for title_html, snippet_html in blocks:
            title = re.sub(r'<[^>]+>', ' ', title_html)
            snippet = re.sub(r'<[^>]+>', ' ', snippet_html)
            title = re.sub(r'\s+', ' ', title).strip(' -:')
            snippet = re.sub(r'\s+', ' ', snippet).strip(' -:')
            if not snippet:
                continue

            address_match = re.search(
                r'([A-ZÀ-ÿa-z0-9\-\.,\s]{15,220}(?:Rua|Avenida|Av\.|Rodovia|Travessa|Alameda|Praça|Estrada)[A-ZÀ-ÿa-z0-9\-\.,\s]{10,260})',
                snippet,
                flags=re.IGNORECASE
            )
            address = address_match.group(1).strip() if address_match else snippet
            if not self._is_candidate_address(address):
                continue

            score = self._score_candidate(account_name, title, snippet)
            candidates.append({
                'address': address,
                'source': f'DuckDuckGo: {title}',
                'score': score,
            })

        return sorted(candidates, key=lambda item: item['score'], reverse=True)

    def find_headquarter_address(self, account_name: str) -> Dict[str, str]:
        account_name = (account_name or '').strip()
        if not account_name:
            raise ValueError('Conta inválida para busca de endereço.')

        self.logger.info('[AutoToca][Address] buscando endereço para conta=%r', account_name)
        candidates = self._extract_candidates_from_duckduckgo(account_name)
        if not candidates:
            return {
                'suggested_address': '',
                'source': 'Não encontrado automaticamente. Preencha manualmente.',
                'confidence': 'low'
            }

        best = candidates[0]
        confidence = 'high' if best['score'] >= 8 else 'medium'
        return {
            'suggested_address': best['address'],
            'source': best['source'],
            'confidence': confidence
        }
