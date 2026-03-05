# Guia de Finalização e Publicação (version3)

Este guia consolida a estratégia para publicar a versão `version3` com instalador “next, next, finish”, preservação de dados e atualização futura.

## 1) Estrutura de pastas e banco de dados (sem perder dados em updates)

**Recomendação prática para Windows:**

- **Binários da aplicação:** `C:\Program Files\TocaDoCoelho\`
- **Dados do usuário (SQLite, uploads, configs):** `C:\ProgramData\TocaDoCoelho\` **ou** `%LOCALAPPDATA%\TocaDoCoelho\`

> Evite manter banco dentro de `Program Files` (pasta protegida/UAC e risco em reinstalação).

### Política sugerida

- O **instalador nunca apaga dados** em `ProgramData` / `LocalAppData`.
- O desinstalador oferece duas opções:
  - “Remover apenas app” (padrão)
  - “Remover app + dados” (opcional explícito)
- O app deve fazer **migração automática** apenas na primeira execução (ex.: de `C:\toca-do-coelho-version2` para o novo caminho).

---

## 2) Instalação 100% automática de dependências (sem terminal)

Para experiência “next, next, finish”, o melhor caminho é:

1. Empacotar em **executável único** com `PyInstaller` (ou Nuitka).
2. Usar instalador como **Inno Setup** ou **NSIS** para copiar arquivos, atalhos e registro.
3. Não depender de Python pré-instalado no PC do usuário.

### Por que isso é importante

- Menos falhas por PATH/Python ausente.
- Instalação consistente em qualquer máquina Windows.
- Menos suporte manual.

---

## 3) Instalação “limpa” (sem seus dados)

Checklist para gerar release limpa:

- Antes do build, garantir que **não existe DB de desenvolvimento** dentro da pasta de build/repo.
- O primeiro start cria banco vazio com schema atual.
- Se quiser dados iniciais, usar somente **seed neutro** (sem clientes reais).
- Revisar `public/` e arquivos do projeto para não incluir exports internos.

---

## 4) Como enviar patches/atualizações

Você tem 2 estratégias (podem coexistir):

### A) Atualizador dentro do app (recomendado)

- App consulta endpoint (`/latest.json`) com versão mais nova.
- Se houver update:
  - baixa instalador assinado
  - fecha app
  - executa upgrade silencioso
- Pode usar: `pyupdater`, fluxo próprio com GitHub Releases/S3/Cloudflare R2.

### B) Canal simples de atualização manual

- “Ajuda > Verificar atualização” abre página de download.
- Menor complexidade inicial.

### Boas práticas obrigatórias

- Versionamento semântico (`1.2.3`).
- Assinar executável/instalador (certificado code-signing).
- Changelog por versão.

---

## 5) Pendências identificadas no código atual (antes de publicar)

### Alta prioridade

1. **Unificar caminho de dados entre app e launcher.**
   - `app.py` usa `C:/toca-do-coelho-version2`.
   - `launcher.py` usa `%AppData%\toca-do-coelho` e nome de DB antigo.

2. **Corrigir instalador NSIS para não depender de `python.exe` do sistema.**
   - Hoje o script chama `$SYSDIR\python.exe`, que pode não existir.

3. **Corrigir nomes de arquivos divergentes no instalador.**
   - NSIS referencia `toca_coelho_icon.ico`, mas no repositório há `coelho_icon_transparent.ico`.

4. **Corrigir script manual quebrado.**
   - `INSTALAR_SIMPLES.bat` copia `launcher_improved.py`, arquivo inexistente.

5. **Atualizar documentação para refletir version3 e caminho final de dados.**
   - README/guia ainda citam caminho antigo em `AppData\Roaming`.

### Média prioridade

6. Definir estratégia para dependências pesadas (Whisper/FFmpeg):
   - incluir binário FFmpeg no pacote **ou** feature opcional com download guiado.

7. Padronizar logs/telemetria de erro para suporte pós-release.

8. Criar rotina de backup automático do SQLite (ex.: diário, retenção 7 dias).

---

## Roteiro recomendado de release (resumo)

1. Congelar branch `version3` e criar checklist de release.
2. Corrigir pendências de caminho/instalador.
3. Gerar build com PyInstaller (`onedir` para facilitar update inicial).
4. Criar instalador (Inno/NSIS) instalando em `Program Files` e dados em `ProgramData`.
5. Testar cenários:
   - instalação limpa
   - upgrade sem perda de dados
   - desinstalação preservando dados
6. Publicar release + changelog + hash SHA256.
7. Ativar checagem de atualização dentro do app.

