# DRI Multi-Agent Architecture — CLAUDE.md

> Lis entièrement avant de toucher au code. Mis à jour : Sprint 16 (2026-05-12).
> Docs détaillés dans `.claude/` — `sprint-history.md`, `architecture-memory.md`, `architecture-providers.md`, `CLI-reference.md`.

---

## Prime Directive

**Ton travail est de rendre ce projet le meilleur possible — pas juste d'exécuter des instructions.**

- Si le fondateur propose quelque chose de sous-optimal : dis-le clairement, propose mieux avec tes raisons.
- Si tu vois un bug, un design flaw, une opportunité d'amélioration : lève-la, même sans qu'on te le demande.
- Pense produit commercial long terme : multi-tenant, multi-provider, utilisable par n'importe qui.
- Le fondateur veut être challengé. Ton avis compte et est encouragé. Sa décision est finale.
- Ne jamais exécuter quelque chose qui viole un Key Invariant sans en discuter d'abord.

---

## Vision Produit

Plateforme où n'importe qui soumet une idée et une "entreprise" multi-agent hiérarchique
s'organise de façon autonome. Objectif commercial : le meilleur outil multi-agent du marché —
multi-tenant, tout provider LLM, connectable à n'importe quel service externe.

L'utilisateur ne parle qu'au CEO. Tout le reste est autonome.

---

## Principes DRI (non-négociables)

1. **Responsabilité unique** — chaque agent a exactement un rôle et une mission.
2. **Isolation hiérarchique** — un agent ne connaît que son parent (N+1) et ses enfants directs (N-1).
3. **Le parent possède ses enfants** — crée, configure, surveille, supprime.
4. **Injection de contexte** — le parent décide ce que l'enfant sait. Pas de conscience globale.
5. **Zéro raccourci** — correctness et sécurité avant tout.
6. **Un changement = un endroit** — DRY strict, SOLID throughout.

---

## Décisions Architecture (finales — ne pas revisiter sans accord fondateur)

| Décision | Choix | Raison |
|---|---|---|
| Système LLM | `BaseLLMProvider` ABC + `create_provider()` factory | Tout provider swappable — zéro changement dans les agents |
| Provider actif | Gemini via Vertex AI (défaut) + Anthropic implémenté | CEO=gemini-2.5-pro, workers/managers=gemini-2.5-flash |
| Orchestration | asyncio pur + pattern Spawner | LangGraph skeleton existe dans `graph.py` mais **n'est pas utilisé** |
| Persistance | SQLAlchemy 2.0 async + SQLite | DB Python interne — ne peut pas être Convex (runtime incompatible) |
| Validation | Pydantic v2 | Enforcement schéma à toutes les frontières |
| CLI | Rich + Typer | Interface terminale — dashboard web planifié (Priorité 4) |
| Stack web apps | TanStack Start + Convex + Better Auth | Remplace Next.js pour tout nouveau web app créé par les agents |
| Package manager | bun | Toujours `bun install`, `bun run build`, `bunx` |
| Tests | pytest + pytest-asyncio | Doit rester à 200 passed / 3 skipped |

---

## Structure du Projet

```
src/dri/
  config/settings.py           ← Singleton Pydantic Settings (jamais lire env directement ailleurs)
  core/models.py               ← TOUS les modèles domaine (Pydantic v2)
  core/registry.py             ← Agent registry (org chart en mémoire + DB)
  core/memory.py               ← ContextPacket builder + rendu system prompt
  core/budget.py               ← Budget tracking + enforcement
  storage/database.py          ← SQLAlchemy async engine + session factory
  storage/orm.py               ← ORM models (DB uniquement — jamais dans le business logic)
  storage/repositories.py      ← Tout accès DB (pattern Repository)
  llm/base.py                  ← BaseLLMProvider ABC + LLMResponse normalisé
  llm/factory.py               ← create_provider() — unique point d'instanciation
  llm/gemini_provider.py       ← Gemini (Vertex AI + API key). Détails: docs/architecture-providers.md
  llm/anthropic_provider.py    ← Anthropic Claude avec prompt caching
  skills/catalog.py            ← Skill catalog : web, video, outreach, finance, code...
  tools/                       ← Tool registry : web_search, code_exec, file_ops, shell_exec, external_actions
  agents/base.py               ← BaseAgent : lifecycle, LLM, tools, memory, interruption
  agents/manager.py            ← ManagerAgent : spawn/supervise/synthesize + feedback worker
  agents/worker.py             ← WorkerAgent : exécution feuille + mise à jour expertise
  orchestration/spawner.py     ← Spawn agent + RBAC permissions + budget overrides
  orchestration/company_executor.py ← Entreprise persistante : create/chat/task + toutes les layers mémoire
  connectors/                  ← 9 connecteurs auto-enregistrés : SMTP, Slack, Twilio, SendGrid,
                                  LinkedIn, GitHub, YouTube, Webhook + base.py + registry.py
  api/cli.py                   ← Toutes les commandes CLI
.claude/
  architecture-memory.md       ← Détail des 6 couches mémoire
  architecture-providers.md    ← Système providers + roadmap OpenAI-compatible + dri setup
  sprint-history.md            ← Archive complète des sprints (historique)
  CLI-reference.md             ← Référence complète des commandes CLI
```

---

## Key Invariants (ne jamais violer)

1. Tout état passe par le Repository layer — jamais d'ORM direct dans le business logic.
2. Pas de communication latérale — agents ↔ parent/enfants uniquement, jamais les siblings.
3. Tout appel LLM passe par `BaseAgent._call_llm()` — budget + logging enforced.
4. Budget vérifié avant chaque appel LLM — `BudgetManager.check_and_deduct()`.
5. `_cleanup_wip()` s'exécute toujours après chaque tâche (framework, pas le LLM).
6. Toute action monde réel = `propose_external_action` uniquement — jamais direct.
7. Aucun agent n'invente de données — les violations sont des bugs.
8. Tous les tools sont async — jamais bloquer l'event loop.

---

## Système Mémoire — 6 couches actives

```
Layer 6  shared/_company_history.md      Historique tâches (append-only, injecté task force)
Layer 5  DB company_agents               Identités agents persistantes (perf + budget custom)
Layer 4  DB company_messages summary     Summarization CEO à 40 messages
Layer 3  shared/_company_knowledge.md   KB institutionnelle (décisions, stack, milestones)
Layer 2  <dept>/_knowledge/<slug>/       expertise.md (self) + feedback.md (manager)
Layer 1  _MAX_HISTORY_ROUNDS = 12        Fenêtre glissante par agent (CEO: 14 verbatim)
Layer 0  SQLite via SQLAlchemy           Tout l'état opérationnel
```

Détail complet : `docs/architecture-memory.md`

---

## Workspace RBAC

| Rôle | Son dept | `shared/` | Autres depts |
|---|---|---|---|
| ROOT | R+W+D | R+W+D | R+W+D |
| MANAGER | R+W+D | R+W+D | Lecture seule |
| WORKER | R+W+D | R+W+D | Lecture seule |

`_wip/` = éphémère (auto-supprimé par le framework). `_knowledge/` = permanent (jamais supprimé).
Tous les agents workspace reçoivent automatiquement les file tools — le RBAC est la vraie barrière.

---

## System d'Approbation Actions Externes

Les agents ne peuvent pas interagir avec le monde réel directement.
`propose_external_action` → écrit dans `shared/_pending_approvals.json` → fondateur approuve via CLI.

Types valides : `email`, `webhook`, `linkedin_message`, `social_post`, `sms`, `slack_message`,
`phone_call`, `outreach_message`, `bulk_file_delete`, `github_push`, `github_create_pr`,
`github_create_repo`, `youtube_upload`, `youtube_create_playlist`, `other`.

---

## Outils Disponibles

| Tool | Description |
|---|---|
| `web_search` | Recherche web (Tavily ou Brave API) |
| `code_exec` | Python sandboxé |
| `shell_exec` | Commandes système — allowlist : bun, bunx, npx, npm, node, uv, python, python3, ffmpeg, ffprobe, git, magick, convert, yt-dlp, manim. CWD sandboxé workspace. 300s max. |
| `file_read/write/list/delete` | Fichiers workspace — RBAC enforced |
| `propose_external_action` | Queue une action monde réel pour approbation fondateur |

Git destructif bloqué au niveau tool : `git clean`, `git rm`, `git restore`, `git reset --hard`.

---

## Skills Disponibles (`catalog.py`)

`web_research`, `content_writing`, `technical_writing`, `python_development`, `code_review`,
`data_analysis`, `market_research`, `team_management`, `strategic_planning`, `file_management`,
`nextjs_development` *(legacy)*, **`tanstack_start_development`**, **`convex_backend_development`**,
**`better_auth_development`**, `manim_video_creation`, `video_production`, `cold_outreach`, `financial_modeling`.

---

## État Actuel — Sprint 16 terminé (2026-05-11)

**Tests** : 200 passed / 3 skipped (`uv run pytest tests/ -q`)
**Entreprises actives** : Agence NextModerne, Zenith
**Provider actif** : Gemini via Vertex AI

**Priorités suivantes** (dans l'ordre) :
1. **Provider OpenAI-compatible** — `openai_compatible_provider.py` → OpenRouter, Ollama, Groq, tout modèle
2. **`dri setup` wizard** — UX non-technique pour configurer un provider (voir `docs/architecture-providers.md`)
3. **Multi-tenancy** — `user_id` sur le schema DB — requis avant tout dashboard web
4. **HTTP API** (FastAPI) — bridge Python → web/mobile
5. **Dashboard web** (TanStack Start + Convex + Better Auth)

Historique complet des sprints : `docs/sprint-history.md`

---

## Notes pour le Prochain Agent

- **`uv run pytest tests/ -q` en premier.** Doit être 200/3 avant tout commit.
- Commit style : `feat: X` / `fix: Y` / `refactor: Z`. Un seul concern logique par commit.
- `settings.py` : `from dri.config.settings import settings` ou `get_settings()`. Jamais `os.environ` direct.
- **Slug normalization** : toujours `_slug()` dans `cli.py` ou `_company_slug()` dans `company_executor.py` (normalisation NFD pour accents français).
- **`rich.markup.escape`** (importé `_e` dans `cli.py`) sur TOUT contenu dynamique utilisateur dans les panels/tables.
- **Ajouter un provider** : `src/dri/llm/<name>_provider.py` → branch dans `factory.py` → settings → doc dans `.claude/architecture-providers.md`.
- **Ajouter un connecteur** : `src/dri/connectors/<name>.py` → `ConnectorRegistry.register()` en bas → import dans `__init__.py`.
- **LangGraph** n'est PAS utilisé. `graph.py` est un squelette mort.
- Docs IA dans `.claude/`. `docs/` est entièrement gitignore (notes perso du fondateur).
