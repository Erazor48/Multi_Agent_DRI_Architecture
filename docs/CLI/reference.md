# DRI — Référence CLI complète

> Toutes les commandes disponibles pour piloter ton système multi-agents.  
> Lanceur : `uv run dri <commande>`  
> Chaque commande accepte `--help` pour afficher les options détaillées.

---

## Vue d'ensemble

```
dri
├── run                          # Session one-shot (une entreprise, une réponse)
├── sessions                     # Historique des sessions passées
├── org                          # Organigramme de la dernière session
└── company                      # Mode entreprise persistante
    ├── create                   # Créer une nouvelle entreprise
    ├── list                     # Lister toutes les entreprises
    ├── chat                     # Parler au CEO en continu
    ├── task                     # Lancer une mission d'équipe directement
    └── approvals                # Gérer les actions externes en attente
        ├── list                 # Voir les actions en attente
        ├── show <N>             # Lire le contenu complet d'une action
        ├── approve <N>          # Approuver une action
        └── reject <N>           # Rejeter une action
```

---

## `dri run` — Session one-shot

Lance une session complète : le CEO crée une entreprise, spawnne ses équipes, produit un rapport, puis s'arrête. Rien n'est persisté entre les sessions.

```bash
uv run dri run
uv run dri run --pitch "Une SaaS pour la gestion d'inventaire restaurant"
uv run dri run -p "Mon idée" --budget 500000
```

| Option | Raccourci | Description |
|--------|-----------|-------------|
| `--pitch TEXT` | `-p` | Pitch à transmettre directement (sinon prompt interactif) |
| `--budget INT` | `-b` | Remplace le budget de tokens de la session (ex: `500000`) |

**Comportement :** Si `--pitch` est omis, le terminal affiche un prompt. Le CEO conçoit la structure, spawne les managers en parallèle, attend tous les résultats, synthétise et retourne. Tout s'arrête ensuite.

---

## `dri sessions` — Historique

Affiche les 10 dernières sessions (one-shot et tâches d'entreprise) avec leur statut, le nom de l'entreprise, les tokens consommés, et la date.

```bash
uv run dri sessions
```

Pas d'options. Le statut peut être `running`, `done`, ou `failed`.

---

## `dri org` — Organigramme

Affiche l'organigramme de la dernière session.

```bash
uv run dri org
```

> Fonctionnalité en cours de développement.

---

## `dri company` — Mode entreprise persistante

Le mode entreprise est le mode principal. L'entreprise est créée une fois et mémorisée en base de données. Tu peux lui parler à n'importe quel moment et elle se souvient de tout l'historique de la conversation.

---

### `dri company create` — Créer une entreprise

Design l'entreprise (nom, vision, départements) et la persiste. Ne spawne pas encore d'agents — utilise `chat` ou `task` ensuite.

```bash
uv run dri company create
uv run dri company create --pitch "Une agence marketing pour startups B2B"
uv run dri company create -p "Momentum : accélérateur de croissance tech"
```

| Option | Raccourci | Description |
|--------|-----------|-------------|
| `--pitch TEXT` | `-p` | Pitch (sinon prompt interactif) |

**Résultat :** Affiche le nom de l'entreprise, sa vision, les départements créés, et son ID. Le workspace est initialisé à `workspace/<slug-entreprise>/`.

---

### `dri company list` — Lister les entreprises

Affiche toutes les entreprises persistantes avec leur ID, nom, vision, nombre de départements, et date de création.

```bash
uv run dri company list
```

Utilise les premiers caractères de l'ID avec `--id` dans les autres commandes.

---

### `dri company chat` — Parler au CEO

Lance une session de chat interactive avec le CEO de l'entreprise. L'historique de la conversation est conservé d'une session à l'autre. Tape `/quit` ou `exit` pour sortir.

```bash
uv run dri company chat
uv run dri company chat --id abc12345
```

| Option | Description |
|--------|-------------|
| `--id TEXT` | ID de l'entreprise (utilise la plus récente si omis) |

**Comportement du CEO :**
- Pour les discussions, questions, et stratégie : répond directement.
- Pour les tâches nécessitant du vrai travail (recherche, contenu, rapports, code) : utilise `spawn_team` en interne pour déléguer à une équipe spécialisée et te rapporte les résultats.
- Pour les actions externes (emails, outreach) : les agents proposent via `propose_external_action` — rien n'est envoyé sans ton approbation.

**Exemple de session :**
```
You: Analyse notre marché cible et produis un rapport
CEO: [spawne une équipe, attend les résultats]
CEO: Rapport produit. Documents créés :
     - shared/market_analysis.md
     - marketing/icp_profile.md
     Pending : aucun
```

---

### `dri company task` — Lancer une mission directe

Spawne une équipe d'agents pour exécuter une tâche spécifique sans passer par le chat. Utile pour des missions ponctuelles.

```bash
uv run dri company task --task "Rédige 5 propositions commerciales pour des clients SaaS"
uv run dri company task -t "Analyse la concurrence et produit un benchmark" --id abc12345
```

| Option | Raccourci | Description |
|--------|-----------|-------------|
| `--task TEXT` | `-t` | Description de la tâche à exécuter **(requis)** |
| `--id TEXT` | | ID de l'entreprise (utilise la plus récente si omis) |

**Différence avec `chat` :** `task` spawne directement une équipe sans passer par le CEO conversationnel. Utile pour des exécutions automatisées ou scriptées.

---

## `dri company approvals` — Actions externes en attente

Quand un agent veut interagir avec le monde réel (envoyer un email, faire de l'outreach, poster sur les réseaux sociaux), il ne le fait **jamais** de lui-même. Il dépose une demande d'approbation que tu dois valider ici.

---

### `dri company approvals list` — Voir les actions en attente

```bash
uv run dri company approvals list
uv run dri company approvals list --id abc12345
uv run dri company approvals list --all
```

| Option | Raccourci | Description |
|--------|-----------|-------------|
| `--id TEXT` | | ID de l'entreprise (utilise la plus récente si omis) |
| `--all` | `-a` | Affiche aussi les actions déjà décidées (approuvées/rejetées) |

**Colonnes affichées :** ID, statut, type d'action, agent proposant, destinataire, objet.

**Statuts possibles :**
- `pending` (jaune) — en attente de ta décision
- `approved` (vert) — approuvée
- `rejected` (rouge) — rejetée

---

### `dri company approvals show <N>` — Lire le contenu complet

Affiche tous les détails d'une action : type, statut, agent proposant, destinataire, objet, **justification stratégique**, et le **contenu intégral** du message proposé.

```bash
uv run dri company approvals show 3
uv run dri company approvals show 3 --id abc12345
```

| Argument | Description |
|----------|-------------|
| `ACTION_ID` | Numéro de l'action à inspecter **(requis)** |

**Toujours utiliser `show` avant `approve`** pour lire exactement ce qui serait envoyé.

---

### `dri company approvals approve <N>` — Approuver

Marque l'action comme approuvée. Une note optionnelle peut être ajoutée pour historique.

```bash
uv run dri company approvals approve 3
uv run dri company approvals approve 3 --note "Validé — ton adapté et pertinent"
uv run dri company approvals approve 3 --id abc12345
```

| Argument | Description |
|----------|-------------|
| `ACTION_ID` | Numéro de l'action à approuver **(requis)** |

| Option | Raccourci | Description |
|--------|-----------|-------------|
| `--note TEXT` | `-n` | Note facultative conservée dans l'historique |
| `--id TEXT` | | ID de l'entreprise |

> **Note :** L'approbation enregistre la décision. L'exécution réelle (envoi d'email, etc.) nécessite une intégration configurée (SendGrid, etc.) qui n'est pas encore branchée — la prochaine étape naturelle du système.

---

### `dri company approvals reject <N>` — Rejeter

Marque l'action comme rejetée. La raison est conservée dans l'historique.

```bash
uv run dri company approvals reject 3
uv run dri company approvals reject 3 --note "Ton trop agressif, à retravailler"
uv run dri company approvals reject 3 --id abc12345 -n "Mauvais destinataire"
```

| Argument | Description |
|----------|-------------|
| `ACTION_ID` | Numéro de l'action à rejeter **(requis)** |

| Option | Raccourci | Description |
|--------|-----------|-------------|
| `--note TEXT` | `-n` | Raison du rejet (recommandé pour le contexte) |
| `--id TEXT` | | ID de l'entreprise |

---

## Workspace

Chaque entreprise persistante a son propre workspace :

```
workspace/
└── <slug-entreprise>/           # ex: workspace/momentum/
    ├── shared/                  # Accès lecture+écriture pour tous les agents
    │   ├── _pending_approvals.json   # Actions externes en attente
    │   └── ...                  # Livrables cross-équipes
    ├── chief-marketing-officer/ # Dossier du CMO et ses workers
    ├── chief-technology-officer/
    ├── chief-strategy-officer/
    └── ...                      # Un dossier par département
```

**Règles d'accès (RBAC) :**

| Rôle | Propre dossier | `shared/` | Reste du workspace |
|------|---------------|-----------|-------------------|
| ROOT (CEO) | Lecture + écriture + suppression | Idem | Idem |
| MANAGER | Lecture + écriture + suppression | Lecture + écriture | Lecture seule |
| WORKER | Lecture + écriture + suppression | Lecture + écriture | Lecture seule |

---

## Configuration (`.env`)

```bash
ANTHROPIC_API_KEY=sk-ant-...          # Obligatoire
DEFAULT_MODEL=claude-sonnet-4-6       # Modèle par défaut pour les agents
ROOT_MODEL=claude-sonnet-4-6          # Modèle du CEO
BUDGET_MAX_TOKENS_PER_SESSION=2000000 # Budget total par session
BUDGET_WARNING_THRESHOLD=0.2          # Alerte à 20% restant
BUDGET_CHILD_DEFAULT_SHARE=0.4        # Part du budget transmise aux enfants
DATABASE_URL=sqlite+aiosqlite:///./dri_company.db
WORKSPACE_DIR=./workspace
MAX_CONCURRENT_AGENTS=20
MAX_SPAWN_DEPTH=10
AGENT_TIMEOUT_SECONDS=300
TAVILY_API_KEY=...                    # Optionnel — pour web_search
```

---

## Flux typique d'utilisation

```bash
# 1. Créer l'entreprise une fois
uv run dri company create -p "Momentum : agence de croissance pour startups tech B2B"

# 2. Récupérer l'ID
uv run dri company list

# 3. Travailler avec le CEO (sessions répétables)
uv run dri company chat --id <ID>

# 4. Lancer des missions spécifiques sans chat
uv run dri company task -t "Produis un rapport sur nos 3 clients pilotes prioritaires"

# 5. Vérifier les actions externes en attente après chaque mission
uv run dri company approvals list

# 6. Lire et décider
uv run dri company approvals show 1
uv run dri company approvals approve 1 --note "OK à envoyer"
uv run dri company approvals reject 2 --note "Reformuler d'abord"

# 7. Consulter l'historique des sessions
uv run dri sessions
```

---

## Règles d'intégrité des agents

Tous les agents du système sont soumis aux règles suivantes (non négociables, dans leur system prompt) :

- **Pas d'invention** — jamais de données, résultats, ou feedbacks fabriqués
- **Honnêteté sur les limites** — si un agent ne peut pas faire quelque chose, il le dit et escalade
- **Actions externes via approbation** — tout ce qui touche le monde réel passe par `propose_external_action` et attend ta validation
- **Exemples clairement marqués** — tout contenu illustratif porte le label `[EXAMPLE — NOT REAL DATA]`
- **Citation des fichiers** — chaque agent liste les fichiers qu'il produit avec leur chemin relatif dans son rapport
