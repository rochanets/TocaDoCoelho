## 🐇 Toca do Coelho 5.7.0.1

Versão de manutenção focada no **instalador**. O sistema em si é o mesmo da 5.7.0.0 — o que muda é a atualização parar de falhar no meio.

### 🔧 Correções

#### Instalador — arquivos travados por outros programas
- A atualização batia em **"Erro ao abrir o arquivo pra gravação: ...\_internal\vcruntime140.dll"** em toda instalação sobre uma versão anterior. O culpado não era o Toca: o Chrome (aberto pelo próprio app) e os processos que ele lança herdam a pasta de instalação no caminho de busca de DLL e ficam com `VCRUNTIME140.dll` mapeada muito depois de o Toca ser encerrado — não havia processo nosso para encerrar.
- O instalador agora **libera esses arquivos antes de extrair**, renomeando a cópia presa para `.toca-old<n>`: no Windows um arquivo em uso não pode ser aberto para escrita, mas pode ser renomeado. Quem estava com a DLL mapeada segue usando a cópia renomeada; o caminho original fica livre e a extração grava normalmente.
- As sobras `.toca-old<n>` são apagadas no começo da atualização seguinte (limpeza best-effort — agendar exclusão para o boot exigiria privilégio de administrador, e este instalador é per-user de propósito).
- Isso encerra um risco silencioso: quem clicava em **Ignorar** no diálogo de erro terminava com a instalação "concluída com sucesso", mas com o runtime C de um build antigo convivendo com os `.pyd` novos — receita de crash depois, sem mensagem que ligasse uma coisa à outra.

### 🎨 Visual

#### Instalador
- A ilustração lateral da tela de boas-vindas passa a usar o coelho com a prancheta, mais alinhado com "registro de atividades" (o coelho correndo continua no cabeçalho das páginas internas e no ícone da janela).
- A tela de conclusão passa a mostrar o coelho comemorando.

### 📦 Instalação

1. Baixe `TocaDoCoelho-5.7.0.1-Setup.exe`.
2. Execute o instalador e siga o assistente.
3. Confira a integridade usando o arquivo `.sha256` publicado junto ao instalador.

> **Atualização:** seus dados são preservados automaticamente. Se o instalador avisar que liberou algum arquivo em uso, é o comportamento esperado desta versão.
