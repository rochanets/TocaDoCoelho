# F8.5 - ensaio, rollback e fechamento

## Resultado esperado

A F8.5 fecha o caminho técnico de produção da Fase 8 sem promover serviços
externos. O workflow `Ensaio de produção (F8.5)` constrói duas imagens:

- candidato a partir do commit do PR, com SHA/versão em labels OCI;
- revisão anterior de `Live`, usada como alvo real do rollback.

O ensaio usa projeto Compose, certificados, senhas, banco, volumes e portas
descartáveis. O trap final remove containers, redes, volumes, certificados e
arquivo de ambiente, inclusive quando uma asserção falha.

## O que o ensaio comprova

1. A imagem candidata corresponde ao SHA declarado.
2. O stack produtivo sobe pelo Compose com PostgreSQL, migration one-shot,
   dois workers web, WAHA, backup e Nginx.
3. HTTP redireciona para HTTPS; o certificado é autossinado e descartável.
4. `/healthz` e `/readyz` passam através do proxy TLS e propagam
   `X-Request-ID`.
5. A migration termina com código zero e o web só fica ready com schema atual.
6. API administrativa sem sessão recebe `401`.
7. O início do SSO gera URL oficial do Entra com state e PKCE; logout limpa a
   sessão. A suíte valida cookie Secure/HttpOnly/SameSite, renovação de sessão,
   allowlist e callback com Microsoft mockada.
8. A suíte valida renovação de token Outlook Graph expirado sem expor o refresh
   token. Nenhuma chamada real à Microsoft é feita na CI.
9. WAHA não publica porta, responde health internamente e entrega webhook HMAC
   ao web. Nenhuma conta é pareada nem mensagem é enviada.
10. O sidecar de backup produz dump verificado; o workflow F8.4 executa também
    checksum, restore em banco descartável, consulta e descarte.
11. O web é recriado com a imagem anterior, o ID da imagem em execução é
    conferido, readiness volta, e então o candidato é promovido novamente.
12. O scanner recusa arquivos sensíveis e padrões conhecidos de credencial no
    conjunto rastreado de código/configuração de produção.

## Rollback

O rollback ensaiado troca somente a imagem web. Migrations não são revertidas:
o schema da Fase 8 segue a estratégia expand/contract e precisa permanecer
compatível com a imagem anterior. A imagem anterior é construída do SHA real
da base do PR, não apenas uma segunda tag do mesmo candidato.
Por isso, `/readyz` rejeita schema atrasado, mas aceita e registra schema mais
novo que o código durante o rollback.

Em produção:

1. identifique a imagem anterior pelo digest/SHA, nunca por `latest`;
2. confirme compatibilidade com `schema_version`;
3. ajuste `TOCA_IMAGE_TAG` para a imagem anterior;
4. recrie o web sem remover volumes;
5. aguarde `/readyz` e execute smoke;
6. preserve logs e `request_id` do incidente;
7. corrija para frente se o schema não for retrocompatível.

## Validações externas obrigatórias

CI não possui tenant, mailbox, telefone ou infraestrutura real. Antes do
primeiro go-live, em janela e ambiente autorizados, um administrador deve:

- concluir login e logout com uma identidade permitida do Entra;
- confirmar renovação da sessão após balanceamento entre workers;
- conectar Outlook, renovar token e ler/enviar uma mensagem de teste aprovada;
- parear uma sessão WAHA de teste, enviar/receber mensagem aprovada e reiniciar
  o sidecar sem novo QR;
- confirmar DNS/certificado público, PostgreSQL/backup externo e alertas do
  fornecedor escolhido.

Esses itens são gates de go-live, não lacunas a serem simuladas com credenciais
reais na CI. A implementação da Fase 8 pode ser integrada; a promoção de
produção continua condicional ao checklist.

## Limites

- Produto permanece CRM interno `single-org`.
- Nenhuma alteração de DNS, Entra, banco gerenciado, secret store, observability
  vendor ou conta WhatsApp é feita automaticamente.
- Fase 9 (multi-org/SaaS/billing/onboarding) não foi iniciada.
