# Architecture Mémoire — DRI Multi-Agent

Détail complet des 6 couches mémoire actives. Résumé dans `CLAUDE.md`.

---

## Vue d'ensemble

```
Layer 6: Company Task History     shared/_company_history.md  (append-only, injecté task force)
Layer 5: Agent Identities         DB company_agents table      (tracking perf + budget custom)
Layer 4: CEO Summarization        DB company_messages summary  (compresse à 40 messages)
Layer 3: Company Knowledge Base   shared/_company_knowledge.md (mémoire institutionnelle)
Layer 2: Role Persistent Memory   <dept>/_knowledge/<slug>/    (expertise + feedback par agent)
Layer 1: Active Context Pruning   _MAX_HISTORY_ROUNDS = 12     (fenêtre glissante par agent)
Layer 0: DB Persistence           SQLite via SQLAlchemy async  (tout l'état opérationnel)
```

---

## Layer 0 — DB Persistence

**Tables** : sessions, agents, tasks, messages, persistent_companies, company_messages, company_agents.

Accès UNIQUEMENT via repositories (`src/dri/storage/repositories.py`).
Jamais d'ORM direct dans le business logic.

---

## Layer 1 — Active Context Pruning

`_MAX_HISTORY_ROUNDS = 12` dans `BaseAgent`.
Seuls les 12 derniers rounds tool-call sont conservés dans l'historique actif.
CEO chat : 14 messages verbatim + préfixe summary optionnel.

---

## Layer 2 — Role Persistent Memory

**Localisation** : `workspace/<company-slug>/<dept>/_knowledge/<agent-title-slug>/`

```
chief-marketing-officer/
  _knowledge/
    chief-marketing-officer/
      expertise.md     ← écrit par le manager lui-même en fin de tâche
      feedback.md      ← écrit par le CEO/parent après évaluation
    seo-specialist/
      expertise.md     ← écrit par le worker en fin de tâche
      feedback.md      ← écrit par le manager après synthèse
```

**Lecture** : `BaseAgent._load_agent_memory()` avant chaque tâche → injecté dans `ContextPacket.agent_memory` → section `## Your Persistent Memory` du system prompt.

**Écriture** :
- `expertise.md` : instruction dans `worker.py` (fin de tâche)
- `feedback.md` : instruction dans `manager.py` (après synthèse, pour chaque worker)

**Invariant** : `_knowledge/` n'est JAMAIS touché par `_cleanup_wip()` et n'apparaît pas dans `_inventory_dept_files()`.

**`memory_dept`** : calculé par `Spawner.spawn()` — managers = leur propre slug, workers = slug du manager parent. Prioritaire sur le scan de permissions dans `AgentMemory.for_agent()`.

---

## Layer 3 — Company Knowledge Base

**Fichier** : `workspace/<company-slug>/shared/_company_knowledge.md`

**Sections standard** :
```
## Strategic Decisions
## Brand & Voice
## Technical Stack
## Completed Milestones
## Lessons Learned
```

**Lecture** : injecté dans chaque task force lead (via `company_kb` dans `Spawner`) + dans CEO chat mode (Gap 2 fix).

**Écriture** : CEO-spawned team après décisions majeures / milestones.

Limite : 6000 chars injectés (truncation depuis la fin pour garder le plus récent).

---

## Layer 4 — CEO Conversation Summarization

**Trigger** : > 40 messages non-summary dans `company_messages`.

**Mécanisme** :
1. `_maybe_summarize_ceo_history()` dans `company_executor.py`.
2. Les messages les plus anciens (hors les 14 derniers) sont compressés en 1 record `role="summary"`.
3. `_build_ceo_messages()` préfixe le summary au premier message de la fenêtre verbatim.

**Cycle** : 40 msgs → summarize → garde 14 verbatim → accumule 26 autres → recommence.

Repository : `CompanyMessageRepository.replace_with_summary()`.

---

## Layer 5 — Persistent Agent Identities

**Table** : `company_agents`

```sql
id, company_id, title, role, dept_slug,
task_count, success_count, token_budget,
notes, status, created_at, last_active_at
```

**Écriture** : `_run_task_force()` après chaque task force — tous les nœuds du registry enregistrés.

**Custom budget** : `token_budget > 0` → appliqué au spawn via `Spawner._budget_overrides`.
Défini via `dri company team promote --budget N`.

**CLI** : `dri company team list / show / note / remove / promote`

---

## Layer 6 — Company Task History

**Fichier** : `workspace/<company-slug>/shared/_company_history.md`

**Format d'entrée** :
```markdown
## 2026-05-11 — Description courte de la tâche
- Team: CMO (Chief Marketing Officer), SEO Specialist, Content Writer
- Outcome: success | partial | failed
- Duration: 142s
- Tokens: 45,230 (estimated $0.12)
```

**Écriture** : `_append_company_history()` dans `company_executor.py` après chaque task force.

**Lecture** :
- Task force lead : 3000 derniers chars injectés comme `## Company Task History` dans la mission.
- CEO chat : chargé entier dans le system prompt (Gap 2 fix).

**Usage par `team show`** : parse `raw.split("\n## ")`, filtre par présence du titre de l'agent.

---

## Ajouter une nouvelle couche mémoire

1. Définir : où ça vit (DB / fichier), qui écrit, qui lit, quand.
2. Écriture : ajouter dans le bon agent (worker.py / manager.py / company_executor.py).
3. Lecture : injecter dans `ContextPacket` ou system prompt.
4. Tests : ajouter dans `tests/unit/` (mock filesystem si fichier).
5. Documenter ici + résumé dans `CLAUDE.md`.
