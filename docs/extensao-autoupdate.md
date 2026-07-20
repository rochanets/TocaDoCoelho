# Auto-update local da extensão AutoToca

A extensão AutoToca se instala e se atualiza **sozinha** no navegador, sem o usuário
baixar, descompactar ou recarregar nada. Tudo é hospedado pelo próprio Toca do Coelho
na máquina local — nada é publicado na internet nem na Chrome Web Store.

## Como funciona

1. No build/release, `scripts/build_extension_crx.py` empacota a extensão como um
   `.crx` **assinado** (formato CRX3) e grava a chave pública em
   `public/autotoca-extension/autotoca-helper.pubkey`. Ambos são versionados no repo
   (como já eram o `.zip`/`.xpi`).
2. Em runtime, `integrations/ext_autoupdate.py`:
   - deriva o **ID determinístico** da extensão a partir da chave pública;
   - serve `GET /ext/updates.xml` (manifesto Omaha) e `GET /ext/autotoca-helper.crx`;
   - grava a política `ExtensionInstallForcelist` do Chrome/Edge/Brave em
     `HKCU\Software\Policies\...`, apontando para `http://localhost:<porta>/ext/updates.xml`.
3. O navegador lê a política, instala a extensão a partir do servidor local e passa a
   checar atualizações periodicamente. Toda nova versão do `.crx` é aplicada sozinha.

Tudo é *best-effort*: em qualquer falha (ou fora do Windows) o app apenas registra no
log e o download manual do `.zip`/`.xpi` continua disponível como plano B.

## A chave de assinatura

- Fica em `secrets/ext_signing_key.pem` (ou onde `--key`/`TOCA_EXT_KEY` apontar).
- **Nunca** é versionada (`.gitignore`).
- Precisa ser a **mesma** entre releases para manter o mesmo ID de extensão.
- Se for perdida: gere outra e rode o build de novo. O único efeito é o ID mudar — o
  app reescreve a política sozinho e o navegador reinstala a extensão uma vez.

## Lançar uma nova versão da extensão

1. Edite os arquivos em `public/autotoca-extension/autotoca-chrome-extension/` e suba a
   `version` no `manifest.json`.
2. Rode o build (precisa de `pip install cryptography`, só na máquina de build):

   ```bash
   python scripts/build_extension_crx.py
   ```

3. Faça commit do `autotoca-helper.crx` e do `autotoca-helper.pubkey` gerados.

Na próxima vez que o usuário abrir o app, o navegador baixa a nova versão sozinho.
