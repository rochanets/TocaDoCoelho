# Skill Emil Kowalski no projeto (Claude) e uso com Codex

## Onde a skill está instalada

A skill está instalada em:

- `.claude/skills/emil-design-eng/SKILL.md`

Ela está no formato de **skill do Claude Code**, com frontmatter e instruções detalhadas de revisão/UI.

## Para que a skill serve

A skill `emil-design-eng` encapsula princípios de **Design Engineering** para elevar qualidade percebida da interface, com foco em:

- microinterações responsivas (ex.: `:active` em botões);
- escolha correta de easing e duração de animação;
- consistência de origem de transformação (`transform-origin`) em popovers;
- prevenção de animações que prejudicam performance percebida;
- formato obrigatório de revisão com tabela `Before | After | Why`.

## O Codex consegue usar essa skill?

**Sim — com adaptação operacional.**

O Codex não consome automaticamente o mecanismo interno de skills do Claude (`.claude/skills/...`), mas consegue usar o conteúdo da skill como **guia de engenharia** se ela for lida como documento de referência durante as tarefas.

Na prática:

1. o agente localiza e lê `.claude/skills/emil-design-eng/SKILL.md`;
2. aplica as regras como checklist em mudanças de UI/CSS/JS;
3. registra no PR quais decisões de animação/polimento foram tomadas.

## Checklist rápido para aplicar no TocaDoCoelho

Use este checklist quando alterar `public/index.html` e estilos associados:

1. **Interação frequente?** Se sim, reduzir/remover animação.
2. **Propósito da animação está explícito?** (feedback, estado, continuidade espacial).
3. **Easing correto?** Preferir `ease-out` em entradas e evitar `ease-in` para UI comum.
4. **Duração adequada?** Preferir < 300ms para UI de uso diário.
5. **Botões com feedback tátil?** Garantir `:active` com `scale(0.95–0.98)`.
6. **Evitar `scale(0)`** em entradas; usar `scale(0.95) + opacity`.
7. **Popover origin-aware?** Usar variável de `transform-origin` do componente.

## Sugestão de workflow no projeto

- Em cada PR com impacto visual, adicionar uma seção: **"UI Polish (Emil skill)"**.
- Descrever 2–5 decisões com a tabela:

| Before | After | Why |
| --- | --- | --- |
| `transition: all 300ms` | `transition: transform 180ms var(--ease-out)` | melhora responsividade e evita animar propriedades desnecessárias |

Isso permite aproveitar a filosofia da skill no Codex sem depender do runtime de skills do Claude.
