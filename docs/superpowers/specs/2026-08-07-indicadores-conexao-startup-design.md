# Indicadores de conexão na abertura (pilha de círculos) — Design

**Data:** 2026-08-07
**Status:** Aprovado pelo usuário

## Objetivo

Substituir o popup automático de conexão do WhatsApp na abertura do app por uma pilha
discreta de 3 círculos de status no canto inferior direito, cobrindo três verificações:
**WhatsApp**, **Outlook (Microsoft Graph)** e **Chaves de integração** (Tavily, OpenRouter, SAI).

## Decisões tomadas (com o usuário)

1. **Círculos substituem o popup** — nenhum modal abre sozinho na abertura; modal só ao clicar.
2. **Chaves:** verificação apenas de "preenchida vs. vazia" (sem teste real contra provedor).
3. **Não configurado ≠ falha:** círculo neutro cinza com traço, some junto com os verdes.
4. **Modal de falha** mostra motivo + ações de correção + botão "Tentar novamente".
5. **Progresso:** marcos reais com animação suave entre eles (cold start do WhatsApp = avanço lento).
6. **Preferência reaproveitada:** o setting `waha_startup_check_enabled` (via
   `GET/PUT /api/whatsapp/startup-check`) vira "Verificar conexões na abertura do sistema";
   desligado = nada roda, nenhum círculo aparece.
7. **Posição:** pilha vertical acima do `#bgTaskIndicator` (coelho), mesma coluna, `right:24px`.

## Arquitetura

Feature **100% frontend** — nenhum endpoint novo. Novo módulo `public/js/connection-status.js`
carregado por `index.html`, consumindo endpoints existentes:

| Verificação | Endpoint(s) | Resultado |
|---|---|---|
| WhatsApp | `GET /api/whatsapp/startup-check`, `GET /api/whatsapp/status` (polling se `starting`) | `connected` → sucesso; `!configured` → neutro; `scan_qr`/`offline`/`stopped`/timeout → falha |
| Outlook | `GET /api/outlook/graph-status` | `connected` → sucesso; `needs_reauth`/`needs_consent`/erro → falha; integração inexistente e sem config → neutro |
| Chaves | `GET /api/config/integrations` | 3 chaves preenchidas → sucesso; alguma vazia → neutro; erro de rede → falha |

### Componente: pilha de círculos

- Container `#connStatusStack`: `position:fixed; right:24px; bottom:~88px` (acima do coelho),
  `z-index` acima dos modais (~10600, abaixo do `#errorPopupStack` em 10700),
  `flex-direction:column; gap:10px; pointer-events:none` (círculos com `pointer-events:auto`).
- Cada círculo: ~48px, fundo branco, ícone central (SVG WhatsApp verde, SVG Outlook azul,
  ✦ para Integrações), anel de progresso em SVG com `stroke` em gradiente verde
  (`linearGradient`) + glow (`filter: drop-shadow`), animado via `stroke-dashoffset`
  com `transition` suave.

### Estados por círculo

- **Em andamento:** anel cresce por marcos reais. Clique abre modal com etapa atual ao vivo.
- **Sucesso:** anel completo + badge de checkmark verde; fade-out (opacity + colapso de
  altura) após 3s; pilha reflui suavemente.
- **Falha:** badge X vermelho piscando (animação CSS); círculo persiste. Clique abre modal
  com motivo + ação (QR WhatsApp / Conectar MS365 / ir a Configurações) + "Tentar novamente"
  (volta o círculo ao estado de progresso e reexecuta a verificação).
- **Neutro (não configurado):** cinza com traço; mesmo fade-out dos verdes; clique leva à
  configuração.

### Marcos de progresso

- WhatsApp: 15% após consulta inicial; se `starting`, avanço lento até ~80% durante polling
  (mesma tolerância atual: até 6 tentativas × 10s); 100% em `connected`.
- Outlook: 30% ao disparar `graph-status`; 100% na resposta.
- Chaves: 30% ao disparar; 100% na resposta.

### Modais

- WhatsApp: reaproveita `openWhatsappConnectModal()` (sem o checkbox "não perguntar mais"
  no fluxo de clique — o controle agora é o toggle das Configurações).
- Outlook: reaproveita `openMicrosoft365Modal()`.
- Integrações: **novo** modal simples listando Tavily / OpenRouter / SAI com status
  preenchida/não preenchida e botão para Configurações.
- Em andamento: mini-modal (ou o próprio modal do serviço) mostrando a etapa corrente.

### Mudanças no código existente

- `connection-check.js`: remover o auto-open (`checkWhatsappConnectionOnStartup` +
  listener `DOMContentLoaded` da linha ~333). Funções de modal permanecem.
- `index.html`: incluir `<script src="/js/connection-status.js">`; atualizar rótulo do
  toggle `waStartupCheckToggle` para "Verificar conexões na abertura do sistema".
- `app.css`: estilos da pilha, círculos, anel, badges, animações (blink do X, fade-out).
- Nenhuma mudança em `routes/*.py` nem no banco.

## Tratamento de erros

- Todas as chamadas em `try/catch` — falha de rede num check marca só aquele círculo como
  falha, nunca quebra a abertura do app.
- Timeout do WhatsApp (esgotadas as tentativas de `starting`) = falha com motivo
  "serviço não respondeu a tempo".

## Teste

- Verificação manual via preview (dev server): estados sucesso/falha/neutro simulados
  (ex.: chave removida, Outlook desconectado), clique em cada estado, fade-out, blink,
  convivência com o indicador do coelho.
