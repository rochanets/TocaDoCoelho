## 🐇 Toca do Coelho 5.5.1.0

### ✨ Novidades

#### Agenda — follow-up de compromissos
- Cada compromisso vinculado a um contato agora permite registrar o follow-up diretamente pela Agenda.
- O formulário de atividade é aberto com contato, assunto e data já preenchidos.
- Compromissos concluídos exibem o selo **Follow-up registrado**.

#### Feedback dentro do sistema
- Novo atalho na barra superior para enviar sugestões e relatar problemas.
- O feedback fica salvo localmente e, quando o Microsoft 365 está conectado, é encaminhado ao administrador com o trecho mais recente do log anexado.
- O envio acontece em segundo plano, com indicação de progresso e orientação quando o Outlook ainda não está conectado.

#### AutoToca — Reembolsos
- Leitura de comprovantes em imagem ou PDF e preenchimento assistido do portal de reembolsos.
- Fluxos de deslocamento, estacionamento e almoço com cliente, com revisão obrigatória antes do envio.
- A automação aproveita a sessão já aberta no navegador e preserva o controle final com o usuário.

#### Extensão AutoToca
- Atualização automática da extensão distribuída com o aplicativo.
- Correções no ciclo de atualização e na limpeza de políticas de versões antigas.

### 🔧 Correções

#### WhatsApp Update
- Corrigidos envios e agendamentos pelo WAHA.
- Melhorado o diagnóstico quando a busca de mensagens recebidas retorna vazia.
- Adicionado aviso quando o WhatsApp está desconectado.

#### Outlook e Feedback
- Corrigida a criação das tabelas `outlook_oauth_attempts`, `chamado_juridico_history` e `feedback` em bancos de dados já existentes.
- Corrigido o envio pelo Microsoft Graph iniciado em tarefas de segundo plano.

#### Banco de dados
- O migrador passa a verificar cada versão individualmente, evitando que bancos vindos de outra linhagem pulem migrações necessárias.
- Novos testes protegem contra tabelas adicionadas sem migração correspondente.

#### Account Planning
- A chave Tavily pode ser fornecida pelo instalador oficial, mantendo a configuração do usuário e a variável de ambiente como opções de maior prioridade.

### 📦 Instalação

1. Baixe `TocaDoCoelho-5.5.1.0-Setup.exe`.
2. Execute o instalador e siga o assistente.
3. Confira a integridade usando o arquivo `.sha256` publicado junto ao instalador.

> **Atualização:** seus dados são preservados automaticamente. Depois da instalação, reinicie o navegador uma vez para garantir a atualização da extensão AutoToca.
