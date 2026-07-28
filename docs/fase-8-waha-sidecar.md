# F8.3 - WAHA sidecar e persistência

## Contrato suportado

Produção possui exatamente um serviço `waha` no
`docker-compose.production.yml`. O desktop não usa esse container: preserva o
`waha-lite` iniciado pelo launcher.

O sidecar usa:

- imagem `devlikeapro/waha:latest-2026.7.1`, fixada em vez de `latest`;
- engine `WEBJS`, compatível com os endpoints e identificadores `@c.us`
  existentes no Toca;
- volume nomeado `waha_sessions` em `/app/.sessions`;
- healthcheck oficial `GET /health`;
- `restart: unless-stopped` e `shm_size: 1gb`;
- rede `backend` para falar com o web e rede `waha_egress` somente para acessar
  o WhatsApp;
- nenhuma porta publicada no host;
- Dashboard e Swagger desligados.

A versão foi conferida em 28/07/2026 no
[Docker Hub oficial](https://hub.docker.com/r/devlikeapro/waha/tags). O
[guia oficial de configuração](https://waha.devlike.pro/docs/how-to/config/)
documenta armazenamento local, API key, webhooks e healthcheck.

## Segredos

Três valores diferentes são obrigatórios e nunca entram no Git:

- `WAHA_API_KEY`: chave aleatória plain, com ao menos 32 caracteres, usada
  somente pelo web no header `X-Api-Key`;
- `WAHA_API_KEY_HASH`: `sha512:<128 hex>`, entregue ao container WAHA;
- `WAHA_WEBHOOK_HMAC_KEY`: outra chave aleatória, usada para assinar webhooks.

Gere a chave plain e a chave HMAC com um gerador criptográfico. Calcule o hash
sem adicionar quebra de linha:

```bash
printf '%s' "$WAHA_API_KEY" | sha512sum
```

O web valida `X-Webhook-Hmac` com HMAC-SHA512 sobre o corpo bruto. O endpoint
precisa ser público para o gate de cookie porque o emissor é o sidecar, mas
requisições sem assinatura válida recebem `401`.

Em produção, URL, chave e sessão são sempre lidas do ambiente. A tela continua
mostrando o estado mascarado, mas não pode alterar configuração gerenciada pelo
deploy.

## Rede e fluxo

```text
Navegador -> Nginx -> web -> http://waha:3000
                         ^
                         |
             webhook HMAC pela rede backend
```

O WAHA não participa da rede `edge` e não possui `ports`. A rede
`waha_egress` permite apenas a saída necessária para o WhatsApp; nenhum serviço
é publicado por ela.

O webhook global envia somente `message.any`, com quatro tentativas e backoff
linear. Isso cobre mensagens recebidas e respostas feitas fora do Toca sem
assinar todos os eventos disponíveis.

## Primeiro QR

1. Preencha um arquivo de ambiente fora do Git a partir de
   `.env.production.example`.
2. Valide sem criar serviços:

   ```bash
   docker compose --env-file /caminho/seguro/toca.env \
     -f docker-compose.production.yml config
   ```

3. No deploy autorizado, suba o stack e aguarde `waha` ficar `healthy`.
4. Entre no Toca como administrador, abra a configuração do WhatsApp e acione
   a conexão. O web cria/inicia a sessão e entrega o QR sem expor Dashboard ou
   API WAHA.
5. Escaneie o QR no telefone e confirme o estado `connected`.

## Reinício e persistência

Reiniciar o container não deve exigir novo QR:

```bash
docker compose --env-file /caminho/seguro/toca.env \
  -f docker-compose.production.yml restart waha
docker compose --env-file /caminho/seguro/toca.env \
  -f docker-compose.production.yml ps waha
```

Depois do healthcheck, a sessão deve voltar a `WORKING`. Nunca execute
`docker compose down -v`: `-v` remove o volume de sessão.

Para forçar um novo pareamento, faça logout explícito da sessão pela API
interna e só então use novamente o fluxo de QR do Toca. Logout remove a
credencial pareada e é uma ação destrutiva; deve ser feito apenas durante uma
janela autorizada.

## Atualização

Não use `latest`. Para atualizar:

1. selecione uma versão publicada e leia o changelog oficial;
2. altere somente a tag fixada;
3. rode os testes e o smoke Docker da PR;
4. valide QR, envio, webhook e reinício em dados/sessão descartáveis;
5. promova a mesma imagem, sem novo pull implícito.

Backup operacional do volume e ensaio completo de rollback pertencem às F8.4 e
F8.5.

## Validação automatizada

O workflow Docker comprova:

- imagem fixada sobe saudável;
- não existe porta WAHA publicada;
- API recusa acesso sem chave e aceita a chave correta;
- web alcança WAHA pela rede privada;
- webhook assinado alcança o web e passa pelo HMAC;
- um marcador no volume sobrevive ao restart do container.

Nenhum teste automático conecta uma conta real ou envia mensagem.
