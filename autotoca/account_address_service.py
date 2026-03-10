import logging
import re
from typing import Dict

import requests


class AccountAddressService:
    def __init__(self, timeout_seconds: int = 10):
        self.timeout_seconds = timeout_seconds
        self.logger = logging.getLogger('toca-do-coelho.autotoca.address')

    def find_headquarter_address(self, account_name: str) -> Dict[str, str]:
        account_name = (account_name or '').strip()
        if not account_name:
            raise ValueError('Conta inválida para busca de endereço.')

        query = f'"{account_name}" endereço sede matriz CNPJ'
        search_url = f'https://duckduckgo.com/html/?q={requests.utils.quote(query)}'
        self.logger.info('[AutoToca][Address] buscando endereço para conta=%r', account_name)

        response = requests.get(
            search_url,
            timeout=self.timeout_seconds,
            headers={'User-Agent': 'Mozilla/5.0 TocaDoCoelho AutoToca'}
        )
        response.raise_for_status()

        match = re.search(r'([A-ZÁÀÃÂÉÊÍÓÔÕÚÜÇ][^<]{20,180}(?:Rua|Avenida|Av\.|Rodovia|Travessa|Alameda|Praça|CEP)[^<]{8,220})', response.text, re.IGNORECASE)
        if match:
            address = re.sub(r'\s+', ' ', match.group(1)).strip(' -:')
            source = 'DuckDuckGo (consulta web institucional)'
        else:
            address = ''
            source = 'Não encontrado automaticamente'

        return {
            'suggested_address': address,
            'source': source,
            'confidence': 'medium' if address else 'low'
        }
