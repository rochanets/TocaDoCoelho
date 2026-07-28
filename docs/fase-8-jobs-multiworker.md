# F8.2 - jobs e múltiplos workers

## Decisão técnica

A F8.2 usa **PostgreSQL advisory locks + claims e estados persistentes no
PostgreSQL**. Redis/RQ e Celery foram avaliados e não entram neste estágio.

| Alternativa | Avaliação |
|---|---|
| PostgreSQL advisory locks + tabelas | Escolhida. Reutiliza o banco obrigatório, não adiciona fornecedor/custo e atende o volume atual de poucos jobs periódicos |
| Redis + RQ | Boa evolução se surgir fila dedicada, muitos consumidores ou necessidade de retry operacional; hoje adicionaria serviço, backup e observabilidade |
| Redis + Celery | Completa para roteamento, agenda e retry complexo, mas desproporcional ao inventário atual |

Gatilhos para reavaliar: fila sustentada, necessidade de escalar executores
independentemente do web, prioridades/roteamento, retries automáticos
sofisticados ou workloads CPU-bound.

## Modelo de coordenação

Cada job possui uma chave estável convertida em `bigint` para
`pg_try_advisory_lock`. O lock é de sessão e fica em uma conexão dedicada
durante toda a execução. Um heartbeat mantém a conexão e
`job_runtime_state` atualizados.

Jobs com efeito externo recebem também `run_key` em
`job_execution_claims`. A claim é gravada antes do efeito:

- sucesso: claim termina como `succeeded`;
- falha/crash: claim permanece `failed`/`running` para revisão e não é repetida
  silenciosamente;
- `skip`: declara que nenhum efeito ocorreu e libera a claim para nova
  tentativa.

As migrations PostgreSQL também usam advisory lock próprio, impedindo workers
do primeiro boot de aplicar o mesmo schema em paralelo.

## Inventário e tratamento

| Executor | Frequência/efeito | Proteção F8.2 | Recuperação |
|---|---|---|---|
| Briefing matinal | Diário, gera PDF e envia Graph | Lock `scheduled:*` + claim de ciclo | Claim ambígua bloqueia repetição; estado visível ao admin |
| Revisão semanal | Janela diária/semanal, envia Graph | Lock + claim de ciclo | Mesmo modelo at-most-once |
| Gatilhos de contexto | A cada sete dias, grava sugestões | Lock + claim de ciclo | Sem duplicação do ciclo |
| Poller inbound/WAHA | Intervalo configurável, lê WAHA e faz upsert | Lock `poller:inbound_whatsapp` | Próximo tick retoma; dedupe por origem permanece |
| Envios agendados | Tick de um minuto, envia WAHA/Graph | Lock do worker + claim atômica por linha | Crash após claim vira `error` para revisão; nunca reenvia automaticamente |
| “Enviar agora” | Ação do usuário, efeito externo | Mesma claim atômica da linha | Corrida retorna 409; estado ambíguo exige revisão |
| Threads de IA/documentos | Sob demanda, resultado para polling | `background_tasks.payload_json` por usuário | Outro worker lê o resultado; após crash fica `interrupted`, sem retry automático |
| Companion | Lease/idempotência próprios desde F7.4/F7.5 | Mantido sem alteração | Contrato Companion v1 |
| Robô Playwright direto | Somente desktop com auth desligada | Continua local | Não existe na imagem web |

## Task store compartilhado

Toda chamada de `_bg_task_set` persiste:

- `status`, `step` e `progress`;
- payload JSON completo, incluindo resultado/erro;
- `owner_id`, `runner_id` e heartbeat;
- expiração configurável.

Os wrappers de Outlook confirm, Portfólio e iAta passaram a usar o mesmo store.
O polling consulta primeiro o cache local e depois o banco, sempre validando o
proprietário. A limpeza de memória continua local; o estado durável expira por
`TOCA_TASK_STATE_TTL_HOURS` (padrão 24 h).

No boot, somente tarefas sem heartbeat há mais de 15 minutos viram
`interrupted`. Assim um worker novo não invalida tarefas recentes de outro
worker.

## Envios agendados

`scheduled_sends` recebeu `claim_token`, `claimed_at` e `attempt_count`. A
transição `pending -> processing` é condicional e commitada antes da chamada
externa.

Essa escolha privilegia **não duplicar**. Se o processo cair entre a chamada
externa e o registro final, não é possível provar se a mensagem saiu; depois de
15 minutos ela vira `error` com orientação de revisão manual. Não existe retry
automático nesse estado.

## Configuração e operação

Produção com mais de um worker exige:

```text
DATABASE_URL=postgresql://...
WEB_CONCURRENCY=2
TOCA_MULTIWORKER_JOBS_ENABLED=1
TOCA_JOB_HEARTBEAT_SECONDS=30
TOCA_TASK_STATE_TTL_HOURS=24
```

O endpoint administrativo `GET /api/admin/jobs/status` mostra o estado atual e
as últimas 100 claims. Ele não permite disparar, repetir ou apagar claims.

`TOCA_DISABLE_BG_JOBS=1` continua disponível para migrations, manutenção e
testes que não devem iniciar loops.

## Limites conscientes

- As threads sob demanda continuam no processo web; o estado é compartilhado,
  mas não há fila/retry automático. Queda resulta em `interrupted` e repetição
  explícita pelo usuário.
- Advisory lock depende da saúde da conexão PostgreSQL. Claims duráveis
  protegem os efeitos at-most-once mesmo se a sessão de lock cair.
- Operações de desbloqueio/retry manual serão parte do runbook da F8.4; a F8.2
  fornece visibilidade, não um botão de repetição perigoso.
