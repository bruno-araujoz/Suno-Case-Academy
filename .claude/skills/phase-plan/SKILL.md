---
name: phase-plan
description: Cria ou atualiza o plano de uma fase em docs/plans/NN-<fase>.md (contexto, decisões, checklist, verificação) e marca o progresso. Use no início e no fim de cada fase ou quando o escopo mudar.
arguments: [fase]
---

Fase: `$fase`

## Planos existentes
!`ls docs/plans/ 2>/dev/null; grep -H -m1 -i "status:" docs/plans/*.md 2>/dev/null`

## Instruções
- **Plano não existe:** crie `docs/plans/NN-$fase.md` (NN = próximo número) com:
  ```
  # Plano NN — <título>
  > Status: **<rascunho | em andamento | concluído>** · atualizado em <AAAA-MM-DD>
  ## Contexto        (por quê, qual problema, ligação com docs/TAPI.md)
  ## Decisões        (decisão — motivo; inclua as descartadas em 1 linha)
  ## Checklist       (- [ ] itens pequenos e verificáveis)
  ## Verificação     (comandos exatos que provam que funciona)
  ## Log             (AAAA-MM-DD: o que mudou e por quê)
  ```
- **Plano existe:** leia, marque itens concluídos com base no código/git log real (não em
  suposição), registre desvios no Log e atualize Status/data. Não reescreva decisões passadas —
  acrescente.
- Mantenha o arquivo enxuto (< 250 linhas); detalhe técnico longo vai para `docs/`.
- Ao final, mostre ao usuário o que mudou no plano em 3–5 bullets.
