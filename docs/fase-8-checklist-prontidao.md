# Checklist de prontidão - fechamento da Fase 8

Data do fechamento técnico: 28/07/2026.

Execução dos gates externos, ambiente online, E2E, decisão de branches e
go-live: [plano de ação pós-Fase 8](plano-acao-pos-fase-8-go-live.md).

## Gates automatizados

- [x] Imagem web não-root, SHA/versão fixados e sem dependências desktop.
- [x] Compose produtivo validado sem portas públicas de PostgreSQL/web/WAHA.
- [x] TLS/reverse proxy exercitado com certificado descartável.
- [x] PostgreSQL obrigatório e schema atual exigido no readiness.
- [x] Migration one-shot serializada antes dos workers web.
- [x] Gunicorn com dois workers e coordenação durável de jobs.
- [x] SSO PKCE, allowlist, logout, cookie seguro e renovação de sessão testados.
- [x] Renovação de token Graph testada com endpoint mockado, sem token em log.
- [x] WAHA privado, API key/hash, HMAC, health e volume exercitados sem conta.
- [x] Backup custom + checksum + retenção + restore descartável comprovados.
- [x] Rollback para a imagem anterior real e roll-forward ensaiados.
- [x] Logs JSON, `request_id`, redaction, probes e painel admin testados.
- [x] Scanner de segredos e proibição de arquivos sensíveis ativos na CI.
- [x] Desktop/SQLite e Toca Companion preservados pela suíte completa.

## Gates externos antes do go-live

- [ ] Host, firewall, DNS e certificado público aprovados.
- [ ] PostgreSQL produtivo, criptografia, capacidade e HA aprovados.
- [ ] Cópia externa criptografada dos backups e alerta de atraso configurados.
- [ ] Login/logout/renovação validados no tenant Entra autorizado.
- [ ] Outlook Graph validado com mailbox e mensagem de teste aprovadas.
- [ ] WAHA validado com telefone/sessão de teste autorizados.
- [ ] Coletor de logs, métricas e alertas recebe os sinais documentados.
- [ ] Dono operacional e janela de rollback formalmente definidos.

## Decisão

**Fechamento técnico da Fase 8: APROVADO após CI verde do PR F8.5.**

**Go-live: CONDICIONAL.** Não promover enquanto qualquer gate externo acima
estiver aberto. A ausência de credenciais/acesso externo nesta entrega é
intencional e respeita os guardrails do roadmap.

Não iniciar a Fase 9 sem decisão explícita de produto.
