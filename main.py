"""
main.py — FastAPI server for AI Co-worker Engine

Run with:
    uvicorn main:app --reload

Endpoints:
    POST /chat          — Send a message to an NPC
    GET  /state/{session_id}/{persona_id}  — Get current NPC state
    POST /reset         — Reset a session
    GET  /health        — Health check
"""

import os
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from agents.npc_agent import NPCAgent
from agents.supervisor import SupervisorAgent

app = FastAPI(
    title="AI Co-worker Engine",
    description="Powers AI NPCs for Edtronaut job simulations",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store (use Redis in production)
sessions: dict[str, dict] = {}


# ------------------------------------------------------------------
# Request / Response schemas
# ------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str
    persona_id: str          # "chro" | "ceo" | "regional_mgr"
    user_message: str
    current_module: str = "module_1"   # "module_1" | "module_2" | "module_3"


class ChatResponse(BaseModel):
    session_id: str
    persona_id: str
    message: str
    state: dict
    safety_flags: dict
    supervisor: dict


class ResetRequest(BaseModel):
    session_id: str
    persona_id: str


# ------------------------------------------------------------------
# Helper: get or create NPC + Supervisor for a session
# ------------------------------------------------------------------

def get_or_create_session(session_id: str, persona_id: str) -> dict:
    key = f"{session_id}:{persona_id}"
    if key not in sessions:
        sessions[key] = {
            "agent": NPCAgent(persona_id=persona_id, session_id=session_id),
            "supervisor": SupervisorAgent(),
        }
    return sessions[key]


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """
    Main endpoint: user sends a message → NPC replies.

    Flow:
    1. Load (or create) NPCAgent for this session + persona
    2. NPCAgent processes message (safety check → LLM → state update)
    3. SupervisorAgent evaluates conversation health
    4. If stuck → Supervisor injects hint into NPC for next turn
    5. Return response + state + supervisor analysis
    """
    try:
        session = get_or_create_session(req.session_id, req.persona_id)
        agent: NPCAgent = session["agent"]
        supervisor: SupervisorAgent = session["supervisor"]

        # Step 1: NPC processes message
        result = await agent.chat(req.user_message)

        # Step 2: Supervisor evaluates (may inject hint for next turn)
        supervisor_result = supervisor.evaluate(
            conversation_history=agent.get_history(),
            current_module=req.current_module,
            npc_agent=agent,
        )

        return ChatResponse(
            session_id=req.session_id,
            persona_id=req.persona_id,
            message=result["message"],
            state=result["state"],
            safety_flags=result["safety_flags"],
            supervisor=supervisor_result,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.get("/state/{session_id}/{persona_id}")
def get_state(session_id: str, persona_id: str):
    """Return current state of an NPC in a session."""
    key = f"{session_id}:{persona_id}"
    if key not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    agent: NPCAgent = sessions[key]["agent"]
    return {
        "state": agent.state,
        "history_length": len(agent.history),
        "persona_id": persona_id,
    }


@app.post("/reset")
def reset_session(req: ResetRequest):
    """Reset conversation for a specific NPC in a session."""
    key = f"{req.session_id}:{req.persona_id}"
    if key in sessions:
        sessions[key]["agent"].reset()
        sessions[key]["supervisor"] = SupervisorAgent()
    return {"status": "reset", "session_id": req.session_id, "persona_id": req.persona_id}


@app.post("/session/new")
def new_session():
    """Generate a new session ID."""
    return {"session_id": str(uuid.uuid4())}
