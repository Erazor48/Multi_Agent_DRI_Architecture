# Sprint History — DRI Multi-Agent Architecture

Archive des sprints complétés. Consulter ce fichier pour comprendre l'historique des décisions.
État actuel dans `CLAUDE.md`.

---

## Sprint 16 (2026-05-11)
- Stack switch : `tanstack_start_development`, `convex_backend_development`, `better_auth_development` ajoutés à `catalog.py`.
- Architecture table mise à jour. Tous les nouveaux web apps agents → TanStack Start + Convex + Better Auth.
- `nextjs_development` conservé pour projets legacy.
- `.gitignore` mis à jour : `docs/` → `docs/personal/` pour tracker les docs architecture.
- CLAUDE.md restructuré (lean ~200 lignes) + Prime Directive + global `~/.claude/CLAUDE.md`.

## Sprint 15 (2026-05-09)
- `dri company team show` : section "Recent missions" (parse `_company_history.md`, filtre par titre, 5 dernières).
- `--watch` WIP indicator : slugs actifs ("● chief-marketing-officer in progress") au lieu de générique.
- `token_budget` custom : confirmé entièrement branché depuis Sprint 4. Note CLAUDE.md obsolète supprimée.
- 200 passed / 3 skipped.

## Sprint 14 (2026-05-09)
- `dri company team list --limit N --role <role>` : pagination + footer.
- `rich.markup.escape()` sur tout contenu dynamique dans CLI (fix accents français).
- `dri company use <name>` : confirmé implémenté (state.py + company_use command).
- 200 passed / 3 skipped.

## Sprint 13 (2026-05-09)
- `dri company status --watch` : polling mode (`--interval`, WIP detection, countdown footer, `_fetch()`/`_render()`).
- Fix : `company_delete` utilise désormais `_resolve_company()` → support prefix.
- Internship Gateway test company supprimée.

## Sprint 12 (2026-05-09)
- P1 : `CompanyExecutor.task()` route via CEO avec marqueur `[DIRECT TASK]` (CEO-aware, historique cohérent). Marqueur strippé avant persistance DB.
- P3 : error log structuré (`shared/_errors.jsonl`) + CLI `dri company errors`.
- P4 : timing + estimation coût dans `_company_history.md` + colonne coût dans `dri company budget`.
- P5 : limites KB truncation relevées (3000→6000 dans executor, 1500→4000 dans memory.py).

## Sprint 11 (2026-05-09)
- Instruction PROGRESS.md dans `worker.py`.
- `manim` ajouté à l'allowlist shell_exec + skill `manim_video_creation`.
- YouTube connector (`youtube_upload`, `youtube_create_playlist`) avec champ `file_path` dans `propose_external_action`.
- Dépendances `google-api-python-client` + `google-auth` ajoutées.
- `.env.example` : section YouTube.

## Sprint 10 (2026-05-09)
- Fix race condition `_cleanup_wip()`.
- `_plan_org()` exploration.
- Worker lit `shared/` avant de démarrer.
- Missions worker structurées.
- 195 passed / 3 skipped.

## Sprints antérieurs (résumé)

### Fixes UX & sécurité (2026-05-01)
- Guard git destructif dans `shell_exec.py` : bloque `git clean`, `git rm`, `git restore`, `git reset --hard/--mixed`, `git checkout -- <file>`.
- Instruction "rogue artifact" supprimée — cleanup dossiers → founder approval uniquement.
- CEO conversation-first : `[NEW CONVERSATION]` + 3 tiers d'exécution.
- CEO "explain before restart" : explique depuis workspace + history avant toute relance.
- CEO live progress : `on_status("CEO thinking... (round N)")`.
- Spawn deduplication : `_spawned_task_keys` set, bloque les doubles spawns.
- Budget borrowing : `BudgetManager.return_unused()` + `add_to_allocation()`.

### Connecteurs (2026-04-27)
- GitHub connector (`github_push`, `github_create_pr`, `github_create_repo`). Requiert `GITHUB_TOKEN`.
- Slack Bot Token connector.
- Twilio SMS connector.
- SendGrid connector.
- LinkedIn connector.
- YouTube connector (Sprint 11).
- GitHub connector E2E validé (2026-05-03) : repo `agence-nextmoderne-docs` créé + doc pushé.

### Infrastructure (2026-04-28→30)
- Memory Layer 2 fix : `memory_dept` dans `ContextPacket`, priorité sur scan permissions.
- Gap 2 fix : CEO chat charge `shared/_company_history.md` (Layer 6 visible en chat).
- Gap 3 fix : `Spawner` accepte `budget_overrides: dict[str, int]`, custom budgets via `team promote`.
- `dri company files` : arbre workspace avec tailles.
- `dri company delete` : atomique (DB + workspace). Supporte `--archive` et `--force`.
- `dri company recover` : scan orphan workspaces, réimport.
- Production DB isolation : fixtures tests avec URL `:memory:`.
- Fix `_inventory_shared_files()` Windows backslash → `str()` au lieu de `.as_posix()`.
- Filtres `node_modules` aux 4 endroits : `_workspace_snapshot()`, `_inventory_dept_files()`, `_inventory_shared_files()`, `FileListTool`.
- Integration tests : `test_company_workflow.py` + `test_persistent_company.py` + `test_full_session.py`.

### Layer 5 — Agent identities (2026-04-26)
- Table `company_agents` : task_count, success_count, token_budget, notes, status.
- `_run_task_force()` enregistre tous les nœuds du registry après chaque task force.
- CLI : `dri company team list / show / note / remove / promote`.

### Layer 6 — Task history (2026-04-26)
- `shared/_company_history.md` append-only. Injecté dans task force lead mission.
- `_append_company_history()` dans `company_executor.py`.

### Fondations (2026-04-24→26)
- Architecture complète : agents, tools, skills, connectors, storage, CLI.
- `shell_exec` tool : allowlist exécutables, CWD sandboxé workspace, 300s max, 20k output cap.
- Approval system : `propose_external_action` → `shared/_pending_approvals.json` → CLI approvals.
- SMTP + Webhook connectors.
- 122 tests unitaires.
