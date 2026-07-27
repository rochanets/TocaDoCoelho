# Toca Companion — contrato v1

Este contrato conecta o Toca web ao agente local que executará automações que
dependem de navegador visível, perfil Microsoft e arquivos temporários. A F7.4
implementou o protocolo e a fila; a F7.5 conectou o executor Playwright do
Chamado Jurídico em `toca_companion.py`.

## Princípios

- o Companion é vinculado a um usuário, não a uma organização inteira;
- códigos de vínculo são aleatórios, expiram e funcionam uma única vez;
- código de vínculo, token do dispositivo e token de lease são armazenados
  somente como SHA-256 com separação de domínio;
- uma tarefa só pode ser retirada por um dispositivo ativo do mesmo usuário;
- arquivos não recebem URL pública: exigem token do dispositivo e lease da
  tarefa;
- o robô pode preencher, mas `allow_submit` é sempre `false`; o envio exige
  revisão e ação humana na janela local;
- tarefas, transições e mensagens ficam persistidas para auditoria;
- a mesma `Idempotency-Key` do mesmo usuário e tipo retorna a tarefa original.

## Vínculo

1. Com sessão web autenticada, `POST /api/companion/pairings` cria um código.
2. O usuário digita o código no Companion.
3. O Companion chama `POST /api/companion/v1/pairings/claim` com:

```json
{
  "pairing_code": "ABCD-EFGH-JKLM",
  "device_name": "Notebook corporativo",
  "platform": "windows",
  "app_version": "1.0.0"
}
```

4. A resposta entrega `device_id` e `device_token` uma única vez. O Companion
   protege o token com DPAPI no Windows ou Fernet com chave local restrita,
   sempre em modo fail-closed e nunca em texto puro.
5. Chamadas seguintes usam `Authorization: Bearer <device_token>`.
6. O usuário pode listar e revogar seus dispositivos por
   `GET /api/companion/devices` e
   `DELETE /api/companion/devices/<device_id>`.

Por padrão, o código expira em 10 minutos.

## Retirada e lease

O Companion consulta `POST /api/companion/v1/tasks/next`. Quando há trabalho,
recebe o payload, metadados dos arquivos, `lease_token` e
`lease_expires_at`. Sem trabalho, recebe HTTP 204.

O lease padrão é de 90 segundos. Toda atualização renova o lease:

```http
PATCH /api/companion/v1/tasks/<task_id>
Authorization: Bearer <device_token>
X-Toca-Task-Lease: <lease_token>
Content-Type: application/json
```

```json
{
  "status": "running",
  "progress": 35,
  "step": "Preenchendo o Microsoft Forms"
}
```

O servidor nunca persiste o lease em claro. Se o lease expirar antes do início,
a tarefa pode ser reenfileirada até o limite de tentativas. Depois de entrar em
execução, a perda do lease termina em falha para impedir repetição silenciosa de
efeitos externos.

## Estados

```text
queued -> leased -> running -> awaiting_user -> succeeded
                   |             |              -> failed
                   |             |              -> cancelled
                   +-----------> failed/cancelled

queued -> cancelled/expired
leased/running/awaiting_user -> cancel_requested -> cancelled/failed
```

Estados terminais: `cancelled`, `succeeded`, `failed` e `expired`.

O cancelamento web usa `POST /api/companion/tasks/<task_id>/cancel`. Tarefas
ainda na fila terminam imediatamente; tarefas ativas recebem
`cancel_requested`, que é devolvido nos heartbeats para o executor encerrar de
forma cooperativa.

## Arquivos

Cada item da tarefa informa:

- `id`;
- `field_key`;
- `original_name`;
- `size_bytes`;
- `sha256`;
- `download_url`.

O download exige o token do dispositivo e o mesmo header
`X-Toca-Task-Lease`. O caminho físico nunca é exposto, e o servidor confirma
que o arquivo permanece dentro do storage privado autorizado.

## Idempotência e auditoria

O web envia `Idempotency-Key` ao criar o chamado. A restrição única
`(owner_id, task_type, idempotency_key)` impede duplicação mesmo entre workers.

`companion_task_events` registra criação, retirada, reentrada na fila,
progresso, transições, cancelamento, expiração e falhas. O usuário pode consultar
o estado e os últimos eventos em `GET /api/companion/tasks/<task_id>`.

## Atualização

`GET /api/companion/v1/manifest` compara a versão instalada com:

- `TOCA_COMPANION_LATEST_VERSION`;
- `TOCA_COMPANION_MIN_VERSION`;
- `TOCA_COMPANION_DOWNLOAD_URL`;
- `TOCA_COMPANION_DOWNLOAD_SHA256`.

Um download só é anunciado quando URL e SHA-256 válido estão presentes. O
executor da F7.5 verifica o hash antes de disponibilizar qualquer atualização.

## Executor local (F7.5)

O runtime do Companion é independente da imagem web:

```powershell
python -m pip install -r requirements-companion.txt
python toca_companion.py pair --server https://toca.exemplo.com --code CODIGO
python toca_companion.py run
```

O executor:

- aceita HTTP somente em `localhost` e não segue redirects autenticados;
- mantém token do dispositivo e lease fora dos logs;
- baixa cada anexo somente da mesma origem do servidor, em diretório temporário;
- confirma tamanho e SHA-256 antes de entregar o caminho ao Playwright;
- renova o lease a cada 25 segundos enquanto a janela aguarda o usuário;
- reflete `awaiting_user`, cancelamento, sucesso e falha na auditoria;
- remove os anexos temporários em qualquer estado terminal;
- nunca clica no botão Enviar. `human_submission_detected` apenas registra que
  o Microsoft Forms observou a ação manual do usuário.

## Limites configuráveis

- `TOCA_COMPANION_PAIRING_TTL_MINUTES`: 5–30, padrão 10;
- `TOCA_COMPANION_TASK_TTL_MINUTES`: 5–120, padrão 30;
- `TOCA_COMPANION_LEASE_SECONDS`: 30–300, padrão 90;
- `TOCA_COMPANION_MAX_CLAIM_ATTEMPTS`: 1–5, padrão 3.
