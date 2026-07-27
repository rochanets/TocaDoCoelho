# Fase 7 - matriz de portabilidade

Inventário iniciado sobre a `Live` no commit `29520b9` e atualizado até a
F7.3 sobre o commit `195ba74`. A Fase 7 preserva o produto como CRM interno
single-org e não antecipa Redis, object storage, produção ou multi-org.

| Área | Implementação atual | Destino | Estado nesta branch | Condições e riscos |
|---|---|---|---|---|
| Relatório de relacionamento | ReportLab em `app.py`; dados protegidos pela ACL de conta | Servidor web | Portado em F7.1 | Não recebe upload; ReportLab/Pillow entram na imagem web |
| Briefing matinal e revisão semanal | `_briefings_to_pdf`; envio pelo Microsoft Graph | Servidor web | Portado em F7.1 | PDF é gerado em memória; tarefas multi-worker continuam sendo tema da Fase 8 |
| Leitura de PDF digital | pdfplumber em iToca, Portfólio e iAta | Servidor web | Portado em F7.2 | Limites de bytes/páginas/tempo/texto, assinatura real e erro controlado para PDF malformado ou sem texto digital |
| Leitura de DOCX | python-docx em iToca e iAta | Servidor web | Portado em F7.2 | ZIP/OOXML validado, limites contra expansão abusiva e rejeição explícita do formato legado `.doc` |
| Imagens | Pillow em avatars, logos de relatório e conversão AutoToca | Servidor web, por fluxo | Parcial | Pillow entra com ReportLab; conversões de uploads não são declaradas portadas até receberem validação própria |
| OCR de PDF escaneado | pytesseract + pypdfium2/pdf2image + binário Tesseract | Worker dedicado, Companion ou serviço | Adiado | CPU/memória altas, timeout, limite de páginas e isolamento de parser ainda não definidos |
| Transcrição de áudio | Azure Speech F0 para ditados web; faster-whisper lazy no desktop | API externa / desktop | Portado em F7.3 | Web limitado a WAV PCM mono 16 kHz, 55 s e 5 h/mês; reuniões longas continuam fora |
| Robô do Chamado Jurídico | Playwright visível, perfil do navegador e arquivos locais | Toca Companion | Delegado | Preservar preenchimento sem envio; contrato, autenticação, fila e auditoria ainda precisam de desenho |
| Outlook PowerShell/COM | Implementação histórica desabilitada; Graph ativo | Microsoft Graph | Mantido desativado | Companion somente se surgir lacuna comprovada do Graph |
| Selenium legado | Imports opcionais sem uso ativo identificado | Descontinuar após confirmação | Candidato | Não adicionar Selenium à imagem web |
| XLSX/OpenPyXL | Exportações/importações e indexação de planilhas | Servidor web | Fora do F7.3 | Requer recorte próprio de validação de uploads e consumo de memória |

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

## Decisões do recorte F7.2

1. Centralizar validação e extração em `document_processing.py`.
2. Aceitar no servidor somente PDF com texto digital e DOCX OOXML válido.
3. Aplicar por documento 10 MB, 50 páginas, 250 mil caracteres e orçamento
   cooperativo de 15 segundos, todos configuráveis por ambiente.
4. Limitar também entradas, tamanho descompactado e taxa de compressão de DOCX.
5. Retornar erros HTTP controlados antes de iniciar tarefas assíncronas.
6. Manter OCR, `.doc`, XLS/XLSX e conversões arbitrárias fora do runtime web;
   com autenticação desligada, o comportamento desktop legado permanece.

## Decisões do recorte F7.3

1. Usar Azure Speech F0 somente para ditados web curtos, sem adicionar
   `faster-whisper`, ONNX, FFmpeg ou o modelo à imagem web.
2. Converter a gravação no navegador para WAV PCM mono, 16 bits e 16 kHz.
3. Interromper a gravação automaticamente em 55 segundos e repetir a validação
   de formato, assinatura, tamanho e duração no servidor.
4. Limitar o consumo registrado pelo Toca a cinco horas por mês, globalmente,
   com reserva atômica em SQLite/PostgreSQL; a cota do próprio Azure permanece
   como proteção final.
5. Manter a chamada síncrona porque o endpoint F0 de áudio curto aceita no
   máximo 60 segundos; transcrição longa/assíncrona não antecipa a Fase 8.
6. Configurar o recurso exclusivamente por `AZURE_SPEECH_KEY` e
   `AZURE_SPEECH_REGION`; áudio e texto transcrito não são persistidos.
7. Preservar o `faster-whisper` e os formatos legados quando
   `TOCA_AUTH_ENABLED` estiver desligado.

## Próximos recortes recomendados

- F7.4: contrato do Companion (auth, vínculo, fila, estados, idempotência,
  expiração, cancelamento, transferência segura, logs e atualização).
- F7.5: execução do robô jurídico no Companion e encerramento formal do COM
  legado.
