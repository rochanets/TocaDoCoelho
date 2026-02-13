# Repositório de imagens do Coelho

- Fonte versionada (texto): `coelho.b64`
- Arquivo servido na interface: `coelho.png`
- Fallback visual: `coelho.svg`

## Como trocar sem erro de arquivo binário na PR
1. Converta seu PNG para Base64 (sem prefixo `data:image/png;base64,`).
2. Substitua o conteúdo de `coelho.b64`.
3. Execute a aplicação: ela gera `coelho.png` automaticamente na inicialização.

Obs.: não é necessário versionar `coelho.png`.
