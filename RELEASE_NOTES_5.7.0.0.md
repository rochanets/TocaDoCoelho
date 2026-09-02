## 🐇 Toca do Coelho 5.7.0.0

### ✨ Novidades

#### WikiToca — redesenho em três submódulos
- Barra de submódulos no padrão AutoToca: **Conhecimentos**, **Documentos** e o novo **Capacitação**, cada um com sua própria busca.
- **Busca por conteúdo dentro dos arquivos** (PDF, DOCX, XLSX, imagens) com destaque do trecho encontrado, filtro por tipo e selo do estado da indexação.
- Indexação assíncrona em segundo plano com barra de progresso e botão de reindexação; documentos reimportados via ZIP também entram no índice.
- **OCR de imagens** e de PDFs escaneados na extração de texto (português + inglês, com fallback).

#### WikiToca — Capacitação
- Instâncias de capacitação com sidebar própria (criar, renomear, excluir) e chat por instância.
- Upload de material com título gerado por IA e indexação em segundo plano; o material fica isolado da base do iToca e do submódulo Documentos.
- **Cascata de resposta**: primeiro os documentos da instância, depois a base do WikiToca, e só então a web — com selo na mensagem indicando de onde veio a resposta.
- Resposta gerada em segundo plano com barra de progresso; encerrar a instância durante a geração cancela a tarefa em vez de deixar a barra girando.

#### Mala Direta — envio de e-mail em lote pela conta Microsoft
- Com a conta conectada via OAuth (Graph), a fila inteira sai de uma vez pela própria caixa do usuário: **Enviar todos via Outlook** ou envio linha a linha.
- Despacho em segundo plano com barra de progresso, intervalo entre envios para respeitar o limite do Graph e confirmação antes do disparo (quantos e-mails e de qual caixa).
- Falha de um destinatário não interrompe a fila; se a autorização cair no meio, o restante é marcado como bloqueado (não tentado).
- **Agendar** também para a fila de e-mail, reaproveitando os envios agendados. O modo legado "Abrir no Outlook" continua disponível.

#### Atividades direto na conta
- Botão **Registrar Atividade** no modal da conta, para registrar sem precisar de um contato específico.
- **Sync Outlook**: e-mails de remetentes não cadastrados agora casam a conta pelo domínio e podem ser importados direto na conta.
- **WhatsApp Update**: varredura dos chats e grupos casando o nome do chat com o nome da conta; conversas de contatos não cadastrados viram sugestão de atividade na conta.

#### iAta — botão "Meu resumo"
- Ao lado de **+ Nova Ata**, abre um modal com período (1 semana, 15 dias, 1 mês, tudo) e seleção de contas.
- Compila atividades, Agenda e Kanban por conta e resume com IA os temas em andamento — material pronto para reportar status.

#### Watcher de feedback
- Novo card em Configurações para acompanhar automaticamente os feedbacks que chegam por e-mail, com análise automática e e-mail de resultado.

#### Guia de primeiro acesso em PDF
- Pop-up na abertura oferece o guia de configuração inicial (33 páginas, um passo por página, com a tela real do sistema e o ponto exato em destaque).
- Checkbox "não perguntar de novo" e link permanente em **Configurações › Ajuda e Atualizações**.

### 🔧 Correções

#### WikiToca
- Importação de conhecimentos por planilha voltou a funcionar no Windows (todo `.xlsx` válido devolvia erro 500).
- Documento `.xlsx` agora pode ser excluído no Windows (o handle da planilha ficava aberto e o DELETE falhava).
- Botão **Baixar** restaurado e a busca deixa de ser perdida ao reordenar a listagem.
- Resumo e follow-up curto param de cair na web quando a resposta está nos próprios documentos.
- Listagem de documentos ficou muito mais leve: não trafega mais o texto extraído a cada troca de aba.

#### WhatsApp
- Envio com a sessão fora do ar mostra orientação acionável (parada / conectando / QR pendente) em vez do erro cru do sidecar, e abre o modal de reconexão preservando a mensagem digitada.

#### Extensão AutoToca (0.9.12)
- A extensão sobrevive à auto-atualização sem o erro cru "Could not establish connection" ao iniciar o robô de Reembolsos.

#### UI
- Barras de progresso do Sync Outlook padronizadas (barra verde de 12px com o coelho correndo e percentual), no lugar da barra fina indeterminada.

### 📦 Instalação

1. Baixe `TocaDoCoelho-5.7.0.0-Setup.exe`.
2. Execute o instalador e siga o assistente.
3. Confira a integridade usando o arquivo `.sha256` publicado junto ao instalador.

> **Atualização:** seus dados são preservados automaticamente. Depois da instalação, reinicie o navegador uma vez para garantir a atualização da extensão AutoToca.
