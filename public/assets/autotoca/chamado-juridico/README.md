## Arquivos de apoio do Chamado Jurídico

Adicione manualmente nesta pasta os PDFs que devem aparecer no bloco **Arquivos de Apoio (se necessário)** do módulo **AutoToca > Chamado Jurídico**.

### Como funciona

- O sistema lista automaticamente todos os arquivos `.pdf` desta pasta.
- Os arquivos **não** são gravados em banco.
- Cada PDF aparecerá na tela com ícone e nome do arquivo.
- Ao clicar, o download será iniciado para o usuário.

### Onde colocar os arquivos

Coloque os PDFs diretamente aqui:

`public/assets/autotoca/chamado-juridico/`

### Observações

- Você pode usar os nomes finais que desejar.
- O frontend buscará a lista pelo endpoint `/api/autotoca/support-files`.
- Somente arquivos com extensão `.pdf` serão exibidos.
