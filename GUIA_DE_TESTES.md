# Guia de Testes — Super Update (Blocos 1–14 + Ajustes)

Roteiro para validar manualmente cada ponto alterado no PR #236. Siga na ordem — alguns testes dependem de dados criados nos anteriores.

## Antes de começar

**Configurações necessárias (Configurações > Integrações):**

| Integração | Necessária para | Observação |
|---|---|---|
| SAI (ou OpenRouter) | Rascunhos IA, briefings, gatilhos, follow-up por e-mail | Regra: SAI primeiro, OpenRouter fallback (exceção: busca web = OpenRouter primeiro) |
| Tavily | Account Planning (Bloco 4) | Sem ela, o botão mostra erro claro (isso também é um teste ✓) |
| WAHA conectado | Pendentes de Resposta, envio direto, agendamento WhatsApp | QR code lido e sessão ativa |
| Outlook (Graph) | Follow-up por e-mail, briefing matinal, revisão de sexta, agendamento de e-mail | ⚠️ **Reconectar a integração uma vez** — o escopo novo `Mail.Send` exige novo consentimento |

**Dica:** rode com `python app.py` e deixe o terminal visível — os logs (`[Database]`, `[Inbound]`, `[Jobs]`, `[Agendados]`) confirmam vários testes.

---

## Bloco 1 — Robustez do banco

| # | Teste | Como fazer | Resultado esperado |
|---|---|---|---|
| 1.1 | Migração de banco antigo | Abrir o app pela primeira vez após o update, com seu banco atual | App abre normal; log mostra `Migração 1..11 aplicada` uma única vez; na segunda abertura, nenhuma migração roda |
| 1.2 | Concorrência sem travar | Disparar um sync de WhatsApp e, durante ele, navegar por Home/Contatos/Contas | Nenhum erro `database is locked` |
| 1.3 | Corte de período do sync | Sincronizar WhatsApp com período "1 dia" perto do fim do dia | Mensagens de ontem à noite não entram mais indevidamente (sem deslocamento de 3h) |
| 1.4 | Task interrompida | Iniciar um sync e fechar o app no meio; reabrir | Log de boot marca a task antiga como `interrupted`; UI não fica órfã |

## Bloco 2 — Logging e testes

| # | Teste | Como fazer | Resultado esperado |
|---|---|---|---|
| 2.1 | Suíte automatizada | `python -m pytest tests/ -v` na pasta do projeto | **33 testes verdes** |
| 2.2 | Erros no app.log | Provocar um erro (ex.: Account Planning sem Tavily) | Erro aparece no `app.log` em `%AppData%\toca-do-coelho` com contexto, não só no console |
| 2.3 | CI | Abrir a aba Actions do GitHub no PR | Workflow "Testes" verde |

## Bloco 3 — Modularização (sem mudança de comportamento)

| # | Teste | Como fazer | Resultado esperado |
|---|---|---|---|
| 3.1 | Regressão geral | Passear por TODAS as abas: Home, iToca, Dashboard, Contatos, Gestão de Conta, Portfólio, Campanha, Atividades, Agenda, Kanban, AutoToca, Configurações | Tudo abre e funciona como antes; sem erro no console (F12) |
| 3.2 | CRUDs principais | Criar/editar/excluir um contato, uma atividade, uma conta, um card de Kanban | Comportamento idêntico ao anterior |
| 3.3 | Build PyInstaller | Rodar o build com o comando atualizado do `PASSO_A_PASSO_BUILD_CMD.md` (novo `--add-data "routes;routes"`) | Executável abre e todas as abas funcionam |

## Bloco 4 — Account Planning

Gestão de Conta > botão **✦ Account Planning**.

| # | Teste | Como fazer | Resultado esperado |
|---|---|---|---|
| 4.1 | Erro sem Tavily | Buscar com a Tavily desconfigurada | Mensagem clara apontando Configurações > Integrações (não tela vazia) |
| 4.1b | Segmentos | Abrir o campo Segmento | Sugestões são áreas de MERCADO (Varejo, Saúde, Pharma, Automobilístico, Serviços...), não cargos |
| 4.2 | Busca real | Empresa real conhecida (ex.: um cliente seu) + segmento; clicar **Mapear Decisores** | Barra verde com coelhinho 🐇; ao final, linhas por candidato com foto (com aviso "aproximada"), nome, cargo, link LinkedIn |
| 4.3 | URLs reais | Clicar no link LinkedIn de 2–3 candidatos | Todos abrem perfis reais (nenhuma URL inventada) |
| 4.4 | Salvar contato | Clicar **Salvar** em um candidato | Contato criado; botão vira **✦ Completar infos** sem recarregar a lista |
| 4.5 | Completar infos | Clicar **Completar infos** | Abre o modal de edição do contato recém-criado |
| 4.6 | Já cadastrado | Buscar uma empresa de um contato que já tem LinkedIn cadastrado | Linha marcada "✓ Já cadastrado", sem botão Salvar |
| 4.7 | Reabrir busca | Selecionar a busca no dropdown "Buscas recentes..." | Resultado reaparece sem nova chamada à Tavily |
| 4.8 | Tema escuro | Trocar para o tema Blue Space e refazer uma busca | Nomes, cargos e avisos dos resultados legíveis |

## Bloco 5 — Radar do Dia

| # | Teste | Como fazer | Resultado esperado |
|---|---|---|---|
| 5.1 | Painel comprimido | Abrir a Home | "📡 Radar do Dia" aparece COMPRIMIDO, com círculo vermelho ao lado do título mostrando o nº de itens; clicar expande/recolhe e não cobre os gráficos |
| 5.2 | Nunca contatado no topo | Criar um contato novo sem atividade | Ele aparece como "Nunca contatado" ANTES de contatos atrasados |
| 5.3 | Threshold por cargo | Configurar regra de status para um cargo (ex.: CEO 3/5 dias) e ter um CEO 6 dias sem contato | Descrição da sugestão cita o limite do cargo, não o padrão |
| 5.4 | Arquivados/frios fora | Arquivar um contato atrasado e atualizar o Radar | Ele some de todas as categorias |
| 5.5 | Concluir repõe | Clicar ✔ em uma sugestão | Ela sai e OUTRA entra no lugar (continua com 8) |
| 5.6 | Adiar | Clicar no relógio | Sugestão some hoje e volta amanhã |
| 5.7 | Agir | Clicar no texto de um "Contato atrasado" | Abre o CARD do contato (perfil), não a janela de atividade |

## Bloco 6 — Pendentes de Resposta

| # | Teste | Como fazer | Resultado esperado |
|---|---|---|---|
| 6.1 | Mensagem recebida | Pedir para um contato cadastrado te mandar um WhatsApp; aguardar 1 ciclo (15 min) ou reiniciar o app | Painel vermelho "💬 Pendentes de Resposta" na Home + badge numérico no menu Home |
| 6.2 | Responder remove | Responder o contato pelo celular; aguardar o próximo ciclo | Item some do painel |
| 6.3 | Marcar manual | Clicar **Respondi** em um item | Item some na hora |
| 6.4 | Webhook (opcional) | Subir o WAHA com o novo `docker-compose.waha.yml` | Mensagem recebida aparece em segundos, sem esperar o polling, e sem duplicar |
| 6.5 | E-mail | Importar e-mails do Outlook havendo e-mail de cliente sem resposta sua | Item com ícone 📧 no mesmo painel |

## Bloco 7 — Follow-ups

| # | Teste | Como fazer | Resultado esperado |
|---|---|---|---|
| 7.1 | Detecção no e-mail | Importar do Outlook um e-mail em que foi combinada uma data ("te retorno na sexta") | Compromisso criado na Agenda, igual ao do WhatsApp |
| 7.2 | Vencido no Radar | Ter um compromisso vencido sem atividade posterior do cliente | Sugestão "⏰ Follow-up vencido" no Radar, que só some ao concluir/adiar |
| 7.3 | Banner na Home | Ter follow-up para hoje | Banner verde no topo do Radar; clicar leva à Agenda |
| 7.4 | Notificação Windows | Rodar pelo instalador/launcher com o app na bandeja e follow-ups no dia | Balão de notificação nativo do Windows ~30s após abrir |

## Bloco 8 — Envio via WAHA

| # | Teste | Como fazer | Resultado esperado |
|---|---|---|---|
| 8.1 | Contato rápido | Perfil do contato > **Contato rápido** > escolher template > **Enviar via WAHA** | Mensagem chega no WhatsApp do contato SEM abrir janela; toast "atividade registrada — desfazer" |
| 8.2 | Desfazer | Clicar **Desfazer** no toast em até 10s | Atividade removida do histórico |
| 8.3 | Variáveis | No Contato rápido, usar os BOTÕES de chave (`<nome do contato>`, `<conta>`, `<cargo>`, `<ultima atividade>`...) | Botões inserem a chave no cursor; no envio, substituídas pelos dados reais |
| 8.4 | Lote | Mala Direta com ~5 contatos > **✦ Enviar todos via WAHA** | Barra 🐇 com progresso por contato; intervalo de 8–15s entre envios; falha em 1 não para a fila; resumo final |
| 8.5 | Limite diário | Configurações: setar `waha_daily_send_limit` = 2 (ou enviar até o limite) | 3º envio recusado com aviso claro; contador "cota WAHA: x/y" no modal |
| 8.6 | Contingência | Botão "Abrir no WhatsApp" continua funcionando | Abre web.whatsapp.com como antes |

## Bloco 9 — Gatilhos com IA

| # | Teste | Como fazer | Resultado esperado |
|---|---|---|---|
| 9.1 | Gatilho de notícia | Ter contas marcadas como target + OpenRouter configurado; disparar `POST /api/suggestions/context-scan` (ou aguardar o job semanal) | Sugestões "📰 Gatilho" com manchete real e fonte no Radar |
| 9.2 | Fluxo 3 cliques | Clicar na sugestão (1) > rascunho gerado automaticamente citando o gatilho e o histórico > **Enviar via WAHA** (2) | Mensagem enviada, atividade registrada, sugestão concluída |

## Bloco 10 — Multithreading

| # | Teste | Como fazer | Resultado esperado |
|---|---|---|---|
| 10.1 | Sinal de risco | Conta target com apenas 1 contato ativo (em dia/atenção) | Card da conta mostra um círculo laranja com "!" ao lado do nome; passar o mouse abre um tooltip OPACO explicando o risco e os níveis ausentes |
| 10.2 | Conta saudável | Conta com contatos ativos em 3+ níveis (C-level, diretoria, gerência) | Sem badge |
| 10.3 | Sugestão com nível | Radar mostra "Mapear mais um decisor na conta X" | Descrição aponta o NÍVEL hierárquico ausente (ex.: C-level), não cargo genérico |
| 10.4 | Ação | Clicar na sugestão | Abre o Account Planning com a empresa já preenchida |

## Bloco 11 — "Siga o campeão" (extensão)

⚠️ Requer instalar a **extensão v0.8.0** (baixe em AutoToca > extensão, ou aguarde o aviso do ajuste 3).

| # | Teste | Como fazer | Resultado esperado |
|---|---|---|---|
| 11.1 | Captura passiva | Com o app aberto, visitar no LinkedIn o perfil de um contato JÁ cadastrado (com URL de LinkedIn no cadastro) | Sem clicar em nada, o console da extensão loga a captura (~4s após carregar) |
| 11.2 | Mudança detectada | Perfil visitado com empresa DIFERENTE da cadastrada | Sugestão "🚀 Fulano mudou para [empresa]" de alta prioridade no Radar |
| 11.3 | Um clique | Na sugestão, clicar **Criar conta + card no Kanban** | Conta criada (se não existia) + card "Oportunidade a explorar" com urgência Alta vinculado ao contato; repetir o clique NÃO duplica |
| 11.4 | Não repete | Após tratar, atualizar o Radar | Sugestão não volta |

## Bloco 12 — Whitespace

| # | Teste | Como fazer | Resultado esperado |
|---|---|---|---|
| 12.1 | Matriz | Portfólio > aba **Whitespace** (com ofertas cadastradas e contas target com serviços) | Tabela contas × ofertas com ✅/⬜ refletindo os serviços reais; textos legíveis em TODOS os temas (testar em Blue Space) |
| 12.2 | Sugestão | Radar mostra "Apresentar [oferta] para a conta X" | A oferta sugerida NÃO está presente na conta |
| 12.3 | Rascunho consultivo | Clicar na sugestão > Gerar rascunho | Texto menciona a oferta ausente E cita o que a conta já usa |

## Bloco 13 — Briefing pré-reunião

⚠️ Reconecte o Outlook antes (novo escopo Mail.Send).

| # | Teste | Como fazer | Resultado esperado |
|---|---|---|---|
| 13.1 | Briefing na Agenda | Agenda > compromisso de reunião > botão **✦ Briefing** | Topo mostra FOTO+nome do contato e LOGO+nome da conta; 6 seções bem alinhadas (bullets com recuo correto); com histórico rico, 3+ seções têm dado real |
| 13.2 | Cache | Fechar e clicar em Briefing de novo | Abre instantâneo (mesmo texto, mesma hora de geração); **Atualizar** regera |
| 13.3 | Sem histórico | Briefing de contato sem atividades | Ainda gera algo minimamente útil |
| 13.4 | E-mail matinal | Ter reunião marcada para hoje e disparar `POST /api/briefings/send-morning-email` (ou aguardar o job após as 7h) | E-mail chega na SUA caixa com PDF anexado contendo os briefings do dia |

## Bloco 14 — Revisão de sexta

| # | Teste | Como fazer | Resultado esperado |
|---|---|---|---|
| 14.1 | Minha Semana | Home > "📅 Minha Semana" > mostrar | Toques da semana, follow-ups criados×cumpridos, contatos que esfriaram e plano da próxima semana por dia útil — números batem com a realidade |
| 14.2 | Envio manual | Botão **Enviar por e-mail agora** | E-mail com PDF chega na sua caixa |
| 14.3 | Job de sexta | Na sexta após meio-dia com o app aberto | E-mail chega automaticamente (uma vez só) |

---

## Ajustes finais

### Ajuste 1 — Envio agendado ⏰

| # | Teste | Como fazer | Resultado esperado |
|---|---|---|---|
| A1.1 | Botão presente | Abrir: Contato rápido, rascunho do Radar, e-mail individual e despacho da Mala Direta | Botão **Agendar** ao lado de enviar nos 4 lugares |
| A1.2 | Agendar próximo | Contato rápido > escrever mensagem > **Agendar** para daqui a 2–3 minutos > manter o app aberto | Ao agendar: atividade com ⏰ aparece no histórico do contato SEM mudar o status dele. No horário: mensagem sai, a atividade perde o ⏰ e vira atividade normal, e o status do contato é atualizado |
| A1.3 | Validações | Tentar agendar para o passado | Recusado com mensagem clara |
| A1.4 | Sistema desligado | Agendar para daqui a 2 min > FECHAR o app > esperar passar o horário > reabrir | Envio NÃO sai sozinho; modal "⏰ Envios agendados pendentes" pergunta se ainda quer enviar |
| A1.5 | Enviar agora / Cancelar | No modal, testar os dois botões | "Enviar agora" dispara na hora (atividade ⏰ vira normal); "Cancelar" descarta e REMOVE a atividade ⏰ do histórico; "Decidir depois" mantém para o próximo login |
| A1.6 | E-mail agendado | Contato com e-mail > Novo e-mail > **Agendar** | No horário, e-mail sai via Outlook (verificar Itens Enviados) + atividade registrada |
| A1.7 | Fila agendada | Mala Direta > despacho > **Agendar** (fila toda) | Todos os itens saem via WAHA no horário |
| A1.8 | Dashboard | Dashboard > WhatsApp e Novo e-mail de um contato | Botão **Agendar** presente nos dois modais, com as chaves `<...>` aplicadas no agendamento |

### Ajuste 2 — Primeiro acesso pós-instalação

| # | Teste | Como fazer | Resultado esperado |
|---|---|---|---|
| A2.1 | Instalação nova | Simular: fechar o app e renomear a pasta `%AppData%\toca-do-coelho` (guarda backup!); abrir o app | Abre DIRETO em Configurações > Cadastro do Usuário, com foco no formulário e mensagem de boas-vindas |
| A2.2 | Só uma vez | Fechar e reabrir (mesmo sem preencher o cadastro) | Não redireciona de novo |
| A2.3 | Update normal | Restaurar sua pasta original e abrir | Home normal, sem redirecionamento |

### Ajuste 3 — Aviso de extensão nova

| # | Teste | Como fazer | Resultado esperado |
|---|---|---|---|
| A3.1 | Update com plugin novo | Com seu banco atual (vindo de update), abrir o app | Modal "🧩 Nova versão da extensão (v0.8.0)" com botão **Baixar extensão** e **Já instalei** |
| A3.2 | Baixar | Clicar em Baixar extensão | Baixa o .zip + dica de instalação (chrome://extensions) |
| A3.3 | Já instalei | Clicar **Já instalei** e reabrir o app | Aviso não aparece mais |
| A3.4 | Instalação nova | No cenário do teste A2.1 | Aviso de extensão NÃO aparece (sem falso alarme) |

---

## Checklist rápido de fumaça (5 min)

1. ☐ App abre sem erro e migra o banco (log)
2. ☐ Home mostra Radar do Dia com sugestões coerentes
3. ☐ Criar contato + atividade funciona como sempre
4. ☐ Enviar 1 WhatsApp via WAHA pelo Contato rápido (com desfazer)
5. ☐ Agendar 1 envio para daqui a 2 min e vê-lo sair
6. ☐ Gerar 1 briefing na Agenda
7. ☐ `python -m pytest tests/` → 33 verdes
