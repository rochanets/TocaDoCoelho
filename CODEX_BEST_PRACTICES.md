# Boas Práticas Codex (TocaDoCoelho)

Este documento registra aprendizados de revisão para mudanças futuras.

## 1) Reutilizar regra de negócio existente
- **Não duplicar lógica** já existente no sistema para status/semáforo.
- Em UI de Mala Direta, usar a mesma função/regra do módulo de boarding (`getStatus`) para manter consistência funcional.

## 2) Evitar thresholds hardcoded
- Evitar valores fixos como `30/60 dias` quando o sistema possui parametrização por usuário.
- Priorizar sempre leitura de configuração vigente (regras por cargo + regra universal).

## 3) Consistência entre módulos
- Componentes visuais de status devem refletir o **status real** do contato em todos os módulos.
- Mudanças em um módulo não devem divergir do comportamento esperado em outro módulo.

## 4) Tooltips e acessibilidade
- Exibir contexto curto e útil no `title`/`aria-label` (ex.: classificação e último contato).
- Manter visual minimalista, sem poluir a interface.

## 5) Checklist de revisão antes do PR
- Confirmar se a implementação segue regras existentes do produto.
- Confirmar que não foram introduzidas regras paralelas/duplicadas.
- Executar ao menos checagens básicas de sanidade antes de finalizar.

## 6) Testes mínimos recomendados
- Rodar validações rápidas (ex.: sintaxe/execução básica) e documentar claramente no PR.
- Quando aplicável, validar comportamento visual no fluxo real da funcionalidade.

## 7) UI Polish com referência da skill Emil
- A skill de design engineering instalada em `.claude/skills/emil-design-eng/SKILL.md` deve ser usada como referência para mudanças de interface, mesmo em tarefas conduzidas pelo Codex.
- Em alterações visuais, documentar decisões de animação no formato `Before | After | Why`.
- Priorizar: feedback tátil em botões (`:active`), durações curtas (<300ms), `ease-out` para entradas e evitar `scale(0)`.
- Ver guia operacional em `docs/EMIL_SKILL_ADAPTACAO_CODEX.md`.
