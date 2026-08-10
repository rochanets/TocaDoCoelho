## 🐇 Toca do Coelho 5.6.0.0

### ✨ Novidades

#### iAta — atas de reunião com IA (novo módulo do AutoToca)
- Geração de atas hierárquicas (gerente → conta → oportunidade) a partir da transcrição da reunião.
- A nova ata usa a ata anterior como base e reconcilia os itens automaticamente, sem perda silenciosa de dados.
- Sugestão de conta do CRM com confirmação do usuário e insights por oportunidade (podem ser desligados).
- Visualização, edição do texto com reparse tolerante a falhas e envio da ata por e-mail com formatação.
- Geração assíncrona em segundo plano, com botão **Minimizar/Cancelar** durante o processamento.
- Transcrições longas são fatiadas automaticamente antes do envio à IA.

#### AutoToca — Relatório Semanal
- Nova subfunção para gerar o relatório semanal, convivendo com os demais módulos do AutoToca.

#### Indicadores de conexão na abertura
- Nova pilha de círculos na tela inicial mostra o estado do WhatsApp, do Outlook e das chaves de integração.
- O modal do WhatsApp não abre mais sozinho na abertura — os círculos assumem esse papel.

#### Tratamento de erros
- Erros agora aparecem em popup persistente acima dos modais, com atalho para reportar direto ao Feedback.

### 🔧 Correções

#### Outlook / Microsoft 365
- Link de consentimento de administrador destrava tenants bloqueados por política.
- O app deixa de forçar `prompt=consent` e passa a respeitar o consentimento já concedido pelo admin.
- OAuth do Microsoft Graph se recupera quando o grant guardado perde a validade.

#### Estabilidade do servidor
- Garantia de instância única na porta do app (o Windows aceitava bind duplicado silenciosamente).
- O launcher falha com mensagem clara quando a porta já está em uso.
- Suporte à variável `TOCA_DB_PATH` para apontar o banco de dados para outro caminho.

#### IA (SAI / OpenRouter)
- Fallback do OpenRouter voltou a funcionar quando o SAI está indisponível; timeout do SAI ampliado.

#### WhatsApp Update
- A cota diária de envios volta a contar pelo dia local.
- "Tentar novamente" deixou de ser inoperante após erro fixado.
- O log do WAHA-lite passa a entrar no export de depuração.

### 📦 Instalação

1. Baixe `TocaDoCoelho-5.6.0.0-Setup.exe`.
2. Execute o instalador e siga o assistente.
3. Confira a integridade usando o arquivo `.sha256` publicado junto ao instalador.

> **Atualização:** seus dados são preservados automaticamente. Depois da instalação, reinicie o navegador uma vez para garantir a atualização da extensão AutoToca.
