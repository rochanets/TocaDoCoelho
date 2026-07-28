# F8.1 - runtime e configuração segura de produção

## Artefatos

- `docker-compose.production.yml`: stack de referência PostgreSQL + web +
  Nginx, com somente 80/443 publicados;
- `deploy/nginx/toca.conf`: terminação TLS, redirect HTTP -> HTTPS, headers de
  proxy e segurança;
- `.env.production.example`: contrato de configuração sem valores reais;
- `/healthz`: liveness do processo, sem banco;
- `/readyz`: readiness com consulta ao banco principal.

O stack é uma referência autogerida e não escolhe fornecedor. Um PostgreSQL
gerenciado pode substituir o serviço `postgres` desde que `DATABASE_URL`
continue usando PostgreSQL e os requisitos de TLS, backup e restore sejam
atendidos nas F8.4/F8.5.

## Preparação local segura

1. Copie `.env.production.example` para um caminho fora do repositório.
2. Substitua todos os valores `REPLACE_ME`.
3. Gere `SECRET_KEY` aleatória com pelo menos 32 caracteres e mantenha-a
   estável entre deploys e workers.
4. Use senha PostgreSQL aleatória e aplique URL encoding ao inseri-la em
   `DATABASE_URL`.
5. Monte `fullchain.pem` e `privkey.pem` a partir de um diretório/secret store
   não versionado.
6. Valide a configuração antes de subir:

```bash
docker compose \
  --env-file /caminho/seguro/toca-production.env \
  -f docker-compose.production.yml config
```

Subir esse stack cria/afeta serviços locais. Deploy em host, banco gerenciado,
DNS e emissão de certificado não fazem parte da F8.1 local.

## Contrato fail-closed

Quando `TOCA_ENV=production`, o processo recusa iniciar se qualquer condição
falhar:

- `SECRET_KEY` ausente, curta ou ainda com marcador de exemplo;
- `DATABASE_URL` não PostgreSQL;
- `TOCA_AUTH_ENABLED` ou `TOCA_COOKIE_SECURE` desligado;
- `TOCA_TRUST_PROXY` desligado;
- `TOCA_COOKIE_SAMESITE` fora de `Lax`, `Strict` ou `None`;
- tenant, client ID ou redirects do Entra ausentes/não HTTPS;
- `WEB_CONCURRENCY` inválido ou, com mais de um worker,
  `TOCA_MULTIWORKER_JOBS_ENABLED` desligado;
- coordenação multi-worker habilitada sem PostgreSQL.

`TOCA_TIMEZONE` define o dia operacional (padrão `America/Sao_Paulo`) para
quotas e agendamentos. Timestamps persistidos pelo envio WAHA permanecem em UTC;
a janela diária é convertida explicitamente, evitando erro na virada de dia.

Fora do modo de produção explícito, o desktop preserva SQLite, login desligado
e segredo local, sem mudança de comportamento.

## Microsoft Entra e Graph

O Toca usa um App Registration público com Authorization Code + PKCE. Portanto
o runtime atual **não recebe client secret nem certificado privado**. Se a
política corporativa exigir confidential client/certificado, isso é mudança de
arquitetura e deve ser aprovada antes da implementação.

Configure no App Registration:

- tenant permitido e client ID via ambiente;
- plataforma Web com
  `https://<host>/api/auth/callback`;
- plataforma Web com
  `https://<host>/api/outlook/oauth/callback`;
- permissões delegadas de identidade `openid profile email User.Read`;
- permissões delegadas do Outlook `offline_access Mail.Read Mail.Send
  User.Read`, com consentimento conforme a política do tenant.

Desenvolvimento e produção devem usar redirects/configurações separados. Não
grave tenant/client ID via UI como substituto silencioso das variáveis do
runtime de produção. Tenant e client ID não são segredos, mas devem ser
controlados como configuração; tokens, senhas, chaves e certificados nunca
entram no Git.

Validações reais de SSO, logout, renovação e Outlook Graph exigem um ambiente
Entra autorizado e ficam como critério da F8.5.

## Probes e rede

- Nginx é a única entrada publicada.
- Web e PostgreSQL se comunicam pela rede interna `backend`; o web também
  participa da rede `edge` sem publicar porta, para acessar Entra, Graph e
  demais integrações HTTPS de saída.
- `/healthz` responde enquanto o processo Flask estiver servindo.
- `/readyz` responde 200 somente quando uma consulta ao banco funciona.
- O healthcheck do container web usa `/readyz`; o do Nginx usa `/healthz`
  através do TLS.

O `ProxyFix` confia em exatamente um proxy e só é ativado por
`TOCA_TRUST_PROXY=1`. O web não deve ser publicado diretamente quando essa
opção estiver ativa.

## Evolução na F8.2

O stack passa a usar dois workers por padrão com
`TOCA_MULTIWORKER_JOBS_ENABLED=1`. Advisory locks, claims duráveis e estado
compartilhado estão documentados em `fase-8-jobs-multiworker.md`.
