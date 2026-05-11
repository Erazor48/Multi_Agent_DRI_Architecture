# Architecture Providers LLM — DRI Multi-Agent

Documentation complète du système de providers. Résumé dans `CLAUDE.md`.

---

## Design

Tous les appels LLM passent par `BaseLLMProvider` (ABC). Les agents ne connaissent jamais le
provider directement. Un seul point d'instanciation : `create_provider()` dans `factory.py`.

```
BaseAgent._call_llm()
    → self._provider.call(system, messages, tools, model, max_tokens)
    → LLMResponse (normalisé, provider-agnostique)
```

**Wire format interne** (Anthropic-compatible, tous les providers convertissent vers/depuis) :
```python
# User text
{"role": "user", "content": "some text"}
# User tool results
{"role": "user", "content": [{"type": "tool_result", "tool_call_id": "id", "content": "result"}]}
# Assistant text + tool calls
{"role": "assistant", "content": [
    {"type": "text", "text": "..."},
    {"type": "tool_use", "id": "id", "name": "tool_name", "input": {...}}
]}
```

---

## Providers implémentés

### Gemini (Google) — actif par défaut
**Fichier** : `src/dri/llm/gemini_provider.py`
**SDK** : `google-genai >= 1.10`

Deux modes :
- **API key** : `GOOGLE_API_KEY` dans `.env`, `USE_VERTEX_AI=false`
- **Vertex AI** : credentials service account JSON, project GCP, location. Recommandé en prod.

Fonctionnalités spéciales :
- `thinking_config`: `include_thoughts=True` → reasoning tokens séparés (non pollués dans `response.text`)
- Retry : 5 tentatives, backoff exponentiel (5s → 60s)

Modèles recommandés :
- CEO : `gemini-2.5-pro` (meilleur raisonnement, quota limité)
- Managers/Workers : `gemini-2.5-flash` (rapide, quota plus large)

### Anthropic Claude — implémenté
**Fichier** : `src/dri/llm/anthropic_provider.py`
**SDK** : `anthropic`

Fonctionnalités :
- Prompt caching sur le system prompt (`cache_control: ephemeral`)
- Wire format déjà Anthropic-compatible → conversion minimale
- Retry : 3 tentatives, backoff 2s → 30s

---

## Providers implémentés (suite)

### OpenAI-compatible — IMPLÉMENTÉ (Sprint 17)
**Fichier** : `src/dri/llm/openai_compatible_provider.py`
**SDK** : `openai` (compatible avec tous les providers ci-dessous)

Ce single provider couvre via `base_url` :
| Provider | base_url | Intérêt |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | GPT-4o, o3 |
| OpenRouter | `https://openrouter.ai/api/v1` | 200+ modèles, un seul compte |
| Groq | `https://api.groq.com/openai/v1` | Ultra-rapide (LLaMA, Mixtral) |
| Together AI | `https://api.together.xyz/v1` | Open source models |
| Ollama | `http://localhost:11434/v1` | Modèles locaux (Llama, Mistral, Hermes...) |
| Fireworks | `https://api.fireworks.ai/inference/v1` | Fast inference |
| Anyscale | `https://api.endpoints.anyscale.com/v1` | LLaMA hosted |

**Conversions clés** :
- Messages : wire format Anthropic-style → OpenAI Chat format (tool results = `role: tool`)
- Tools : `input_schema` → `parameters`, wrappé dans `{"type": "function", "function": {...}}`
- Réponse : `finish_reason="tool_calls"` → `stop_reason="tool_use"`

**Ajout dans `factory.py`** : déjà branché — `if s.llm_provider == "openai_compatible"`.

**Settings** : `OPENAI_COMPATIBLE_BASE_URL`, `OPENAI_COMPATIBLE_API_KEY`,
`OPENAI_COMPATIBLE_DEFAULT_MODEL`, `OPENAI_COMPATIBLE_ROOT_MODEL` (optionnel).

---

## Configuration `.env` — état actuel

```bash
# Provider actif
LLM_PROVIDER=gemini          # gemini | anthropic | openai_compatible (bientôt)

# Gemini
GOOGLE_API_KEY=              # API key directe (si USE_VERTEX_AI=false)
USE_VERTEX_AI=true           # Vertex AI recommandé en prod
VERTEX_PROJECT=              # GCP project ID
VERTEX_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=./credentials/service-account.json

# Anthropic
ANTHROPIC_API_KEY=

# OpenAI-compatible (futur)
OPENAI_COMPATIBLE_API_KEY=
OPENAI_COMPATIBLE_BASE_URL=  # ex: https://openrouter.ai/api/v1

# Modèles
DEFAULT_MODEL=gemini-2.5-flash    # managers + workers
ROOT_MODEL=gemini-2.5-pro         # CEO uniquement
```

---

## UX non-technique — `dri setup` (IMPLÉMENTÉ Sprint 17)

Pour qu'une personne non-technique puisse configurer un provider sans toucher `.env` :

```
$ uv run dri setup

Bienvenue dans DRI — Configuration initiale
============================================

Quel service IA voulez-vous utiliser ?
  1. Google Gemini (recommandé — meilleur rapport qualité/prix)
  2. Anthropic Claude
  3. OpenAI / ChatGPT
  4. OpenRouter (accès à 200+ modèles avec un seul compte)
  5. Modèle local avec Ollama (gratuit, tourne sur votre PC)

> Votre choix : 1

Entrez votre clé API Google :
> ****************************

✓ Connexion testée avec succès.
✓ Fichier .env mis à jour.

Votre assistant est prêt. Lancez : uv run dri company create
```

**Implémentation** : nouvelle commande `setup` dans `cli.py` — wizard interactif Typer,
génère/met à jour `.env`, teste la connexion via un appel minimal au provider.

---

## Ajouter un nouveau provider

1. Créer `src/dri/llm/<name>_provider.py` qui hérite de `BaseLLMProvider`.
2. Implémenter `async def call(...)` → retourner `LLMResponse`.
3. Ajouter un branch `if s.llm_provider == "<name>":` dans `factory.py`.
4. Ajouter les settings correspondants dans `config/settings.py`.
5. Documenter dans cette page.
6. Tests : `tests/unit/test_<name>_provider.py` (mock le SDK, pas d'appel réseau).
