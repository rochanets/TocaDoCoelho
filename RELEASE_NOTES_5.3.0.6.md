# 🐇 Toca do Coelho v5.3.0.6

**Data:** 23 de junho de 2026

---

## ✨ Novidades

### Outlook — Sincronização Inteligente
- Agrupa threads de e-mail por assunto com resumo consolidado via IA
- Deduplicação persistente: e-mails já importados não reaparecem em sessões futuras
- Suporte a múltiplos destinatários (CC e BCC) na importação
- Popup branded com resultado detalhado após sincronização

---

## 🔧 Correções

### WhatsApp Update
- Elimina processo Chrome órfão ao iniciar e ao reciclar a sessão
- Corrigido crash `EADDRINUSE` no restart do WAHA-lite
- Watchdog agora recicla corretamente sessão travada após autenticar
- Permite fixar versão do WhatsApp Web (`webVersionCache`) para contornar bug de 99%/LOGOUT
- Logging detalhado para diagnóstico de sessões travadas

### Segurança
- Permissões do arquivo SQLite restritas ao usuário atual do sistema operacional
- Corrigidos achados SAST: PKCE, DPAPI, remoção de PowerShell/COM e `client_secret` no frontend

### Contas
- Excluir conta agora move para arquivo em vez de apagar permanentemente
- Corrigida duplicação ao renomear conta

### iAta / IA
- SAI agora é o provedor primário de LLM; OpenRouter como fallback
- Integração SAI corrigida: migrada de `urllib` para `requests` em todas as funções
- Logging de sucesso adicionado em todas as chamadas SAI

### UI
- Ajustes no modal Preparar Reunião e Relationship Report
- Ícone do Outlook corrigido na barra lateral

---

## 📦 Instalação

1. Baixe `TocaDoCoelho-5.3.0.6-Setup.exe`
2. Execute e siga o assistente (next, next, finish)
3. Verifique a integridade com o arquivo `.sha256`

> **Atualização:** o instalador preserva seus dados automaticamente. Nenhuma migração necessária.

---

## 📋 Notas de Compatibilidade

- ✅ Compatível com banco de dados v5.3.x
- ✅ Dados preservados em `%AppData%\toca-do-coelho`
- ✅ Configurações anteriores mantidas após atualização

---

**Status:** ✅ Release Estável
