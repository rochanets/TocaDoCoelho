## 🐇 Toca do Coelho 5.7.0.0

### ✨ Novidades

#### WikiToca — redesenho em três submódulos
- Barra de submódulos no padrão AutoToca: **Conhecimentos**, **Documentos** e **Capacitação**, cada um com busca própria.
- **Busca por conteúdo dentro dos arquivos** (PDF, DOCX, XLSX, TXT e imagens), com trecho destacado no resultado e filtro por tipo de arquivo.
- Indexação automática em segundo plano ao subir o documento, com selo do estado da indexação e botão de reindexar.
- **OCR de imagens** na extração de texto: prints e fotos passam a ser pesquisáveis.
- Correções de usabilidade: botão **Baixar** de volta na listagem e a busca preservada ao trocar a ordenação.

#### WikiToca — Capacitação (novo submódulo)
- Instâncias de capacitação com CRUD completo e sidebar de seleção.
- Documentos próprios da instância (isolados dos Documentos gerais e da base do iToca), com **título gerado por IA** no upload.
- Chat que responde em cascata: **documentos da instância → base do WikiToca → web**, com selo indicando a origem de cada resposta.
- Ranking de trechos por relevância antes de chamar a IA, para respostas mais ancoradas no material enviado.

#### Mala Direta — envio em lote pela conta Microsoft
- Com a conta conectada via OAuth (Graph), a fila inteira sai pela própria caixa do usuário — sem o antigo "abrir no Outlook" contato por contato.
- Despacho em segundo plano com barra de progresso, intervalo aleatório entre envios para respeitar o limite do Graph e registro de atividade por e-mail enviado.
- Falha em um destinatário não interrompe a fila; se a autorização cair no meio, o restante é marcado como **bloqueado** (não tentado).

#### Watcher de feedback
- Novo card nas Configurações para ligar/desligar o watcher e ajustar seus parâmetros.
- Varredura da caixa de entrada em busca de feedbacks do Toca, com análise automática via Claude Code em worktree isolado e e-mail com o resultado.
- Disponível apenas para o perfil autorizado.

#### iAta — "Meu resumo"
- Botão ao lado de **+ Nova Ata**: escolhe o período (1 semana, 15 dias, 1 mês ou todo o período) e as contas, e a IA resume os temas em andamento de cada conta — material pronto para reportar status.

#### Atividades direto na conta
- Botão **Registrar Atividade** no modal da conta, sem precisar de um contato específico.
- Sync Outlook: e-mails de remetentes não cadastrados agora casam a conta pelo domínio e podem ser importados direto nela.
- WhatsApp Update: varredura de chats e grupos casando o nome da conversa com o nome da conta, virando sugestão de atividade na conta.

### 🔧 Correções

#### WikiToca
- Importação de conhecimentos e exclusão de documentos `.xlsx` voltaram a funcionar no Windows (arquivo travado pelo processo).
- Resumo e follow-up curto param de cair para a web quando a resposta está nos próprios documentos.
- Migração renumerada de 19 para 33 — a numeração anterior colidia com a linhagem de migrações da `main` e era pulada em silêncio, deixando as tabelas sem criar.
- Busca endurecida: termos que normalizam para vazio, ligaduras/símbolos no destaque do trecho e conteúdo malicioso no snippet.

#### WhatsApp Update
- Erro de sessão parada no envio agora é traduzido e oferece reconexão em vez de mensagem crua.

#### Extensão AutoToca
- A extensão sobrevive à própria auto-atualização sem despejar erro de conexão na tela.

#### Interface
- Barras de progresso do Sync Outlook padronizadas com o coelho verde correndo.

### 📦 Instalação

1. Baixe `TocaDoCoelho-5.7.0.0-Setup.exe`.
2. Execute o instalador e siga o assistente.
3. Confira a integridade usando o arquivo `.sha256` publicado junto ao instalador.

> **Atualização:** seus dados são preservados automaticamente. Depois da instalação, reinicie o navegador uma vez para garantir a atualização da extensão AutoToca.
