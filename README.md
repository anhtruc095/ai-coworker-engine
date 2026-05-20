# AI Co-worker Engine

> Powering AI NPCs for Edtronaut job simulations — built for the AI Engineer Intern take-home assignment.

## What this is

An engine that makes AI characters feel like real co-workers: each NPC has a **distinct persona**, **persistent emotional state**, and a **Supervisor Agent** that silently keeps the simulation on track.

Built for the Gucci Group HRM simulation as the reference example — but designed to be reusable across any simulation.

---

## Architecture

```
User (Simulation UI)
        │
        ▼
FastAPI Gateway  ──── Safety filter ──── Session manager
        │
        ▼
Orchestration Layer
  ├── Supervisor Agent  (invisible — monitors, injects hints)
  └── NPC Agents
        ├── CEO        (Marco Bianchi)
        ├── CHRO       (Isabella Ferrante)   ← main demo
        └── Regional Manager (Sophie Laurent)
        │
        ▼
Infrastructure
  ├── LLM API  (Claude Sonnet)
  ├── FAISS    (vector store for RAG)
  └── Redis    (session state cache)
```

---

## Quickstart

### 1. Clone & install

```bash
git clone https://github.com/your-username/ai-coworker-engine
cd ai-coworker-engine
pip install -r requirements.txt
```

### 2. Set your API key

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### 3. Run unit tests (no API key needed)

```bash
python tests/test_npc_agent.py
```

### 4. Start the server

```bash
uvicorn main:app --reload
```

API docs at: http://localhost:8000/docs

### 5. Send a message

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "demo-001",
    "persona_id": "chro",
    "user_message": "Tell me about the competency framework",
    "current_module": "module_1"
  }'
```

---

## Key Design Decisions

### Why FAISS over Pinecone?
FAISS runs locally with zero cost — ideal for a prototype. Pinecone adds managed infrastructure but isn't needed until scale requires it.

### Why Claude Sonnet?
Strong instruction-following means persona constraints hold reliably. Haiku is used for cheap internal calls (Supervisor progress checks).

### Latency strategy
Three-tier response: cache hit (< 200ms) → fast path (< 1.5s) → full RAG (2–4s). Most turns hit tier 1 or 2.

### State management
State lives in memory per session (dict). Production would use Redis with TTL. State is never sent to the user directly — only the NPC's message.

---

## Folder structure

```
ai-coworker-engine/
├── main.py                  FastAPI server
├── requirements.txt
├── .env.example
├── agents/
│   ├── npc_agent.py         Core NPCAgent class
│   ├── supervisor.py        Supervisor/Director agent
│   └── personas/
│       ├── chro.py
│       ├── ceo.py
│       └── regional_mgr.py
└── tests/
    └── test_npc_agent.py    Unit tests + live demo
```

---

## Evaluation notes

| Criterion | Approach |
|---|---|
| Role-playing fidelity | Per-persona system prompts with hidden constraints + emotional state modifiers |
| Architecture soundness | 4-layer design (Frontend → Gateway → Orchestration → Infra), horizontally scalable |
| Edge cases | Jailbreak detection, off-topic redirect, brand autonomy pushback, stuck detection |
| Scalability | Persona registry pattern — add new NPCs by adding one config file |

---

*Built by Ton Anh Truc — AI Engineer Intern application, Edtronaut*
