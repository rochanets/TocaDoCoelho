# Fase 7 - matriz de portabilidade

Inventário realizado sobre a `Live` no commit `29520b9`. A Fase 7 preserva o
produto como CRM interno single-org e não antecipa Redis, object storage,
produção ou multi-org.

| Área | Implementação atual | Destino | Estado nesta branch | Condições e riscos |
|---|---|---|---|---|
| Relatório de relacionamento | ReportLab em `app.py`; dados protegidos pela ACL de conta | Servidor web | Portado em F7.1 | Não recebe upload; ReportLab/Pillow entram na imagem web |
| Briefing matinal e revisão semanal | `_briefings_to_pdf`; envio pelo Microsoft Graph | Servidor web | Portado em F7.1 | PDF é gerado em memória; tarefas multi-worker continuam sendo tema da Fase 8 |
| Leitura de PDF digital | pdfplumber em iToca, Portfólio e iAta | Servidor web | Adiado | Antes de ativar: limite de bytes/páginas/tempo, MIME real e tratamento de PDF malformado |
| Leitura de DOCX | python-docx em iToca e iAta | Servidor web | Adiado | Aceitar somente DOCX validado; `python-docx` não lê o formato legado `.doc` |
| Imagens | Pillow em avatars, logos de relatório e conversão AutoToca | Servidor web, por fluxo | Parcial | Pillow entra com ReportLab; conversões de uploads não são declaradas portadas até receberem validação própria |
| OCR de PDF escaneado | pytesseract + pypdfium2/pdf2image + binário Tesseract | Worker dedicado, Companion ou serviço | Adiado | CPU/memória altas, timeout, limite de páginas e isolamento de parser ainda não definidos |
| Transcrição de áudio | faster-whisper lazy, modelo `base` CPU e endpoint síncrono | Decisão de produto | Bloqueado | Escolher servidor assíncrono, Companion ou API externa; não entra na imagem web core |
| Robô do Chamado Jurídico | Playwright visível, perfil do navegador e arquivos locais | Toca Companion | Delegado | Preservar preenchimento sem envio; contrato, autenticação, fila e auditoria ainda precisam de desenho |
| Outlook PowerShell/COM | Implementação histórica desabilitada; Graph ativo | Microsoft Graph | Mantido desativado | Companion somente se surgir lacuna comprovada do Graph |
| Selenium legado | Imports opcionais sem uso ativo identificado | Descontinuar após confirmação | Candidato | Não adicionar Selenium à imagem web |
| XLSX/OpenPyXL | Exportações/importações e indexação de planilhas | Servidor web | Fora do F7.1 | Requer recorte próprio de validação de uploads e consumo de memória |

## Decisões do recorte F7.1

1. Portar somente geração de PDFs core com ReportLab.
2. Declarar Pillow explicitamente porque os relatórios podem incorporar imagens
   locais já autorizadas; isso não aprova conversões arbitrárias de uploads.
3. Manter imports opcionais e resposta HTTP 503 controlada se ReportLab não
   estiver disponível.
4. Limitar requisições multipart autenticadas na web a 25 MB por padrão,
   configurável por `TOCA_WEB_MAX_UPLOAD_BYTES`; o desktop permanece inalterado.
5. Não adicionar pdfplumber, python-docx, OCR, Whisper, Playwright, Selenium ou
   pywin32 à imagem web neste recorte.
6. Não alterar migrations, persistência, Redis/jobs ou a arquitetura do
   Companion.

## Próximos recortes recomendados

- F7.2: camada central de validação de documentos e leitura de PDF digital/DOCX.
- F7.3: decisão de execução e contrato assíncrono da transcrição.
- F7.4: contrato do Companion (auth, vínculo, fila, estados, idempotência,
  expiração, cancelamento, transferência segura, logs e atualização).
- F7.5: execução do robô jurídico no Companion e encerramento formal do COM
  legado.
