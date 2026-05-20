"""
NPCAgent — Core class for AI Co-worker Engine
Each NPC is a stateful agent with persona, memory, and optional tools.

Usage:
    agent = NPCAgent(persona_id="chro")
    result = await agent.chat(user_message="Tell me about the competency framework")
    print(result["message"])
"""

import os
import json
import time
from typing import Optional
from anthropic import Anthropic
from agents.personas.chro import CHRO_PERSONA
from agents.personas.ceo import CEO_PERSONA
from agents.personas.regional_mgr import REGIONAL_MGR_PERSONA

# Map persona_id → persona config
PERSONA_REGISTRY = {
    "chro": CHRO_PERSONA,
    "ceo": CEO_PERSONA,
    "regional_mgr": REGIONAL_MGR_PERSONA,
}

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


class NPCAgent:
    """
    A single AI Co-worker / NPC with persistent state across a session.

    Attributes:
        persona_id: Which character this agent plays (e.g. "chro")
        state: Emotional state, trust score, topics discussed, etc.
        history: Full conversation history (list of {role, content} dicts)
    """

    def __init__(self, persona_id: str, session_id: Optional[str] = None):
        if persona_id not in PERSONA_REGISTRY:
            raise ValueError(
                f"Unknown persona '{persona_id}'. "
                f"Choose from: {list(PERSONA_REGISTRY.keys())}"
            )

        self.persona_id = persona_id
        self.session_id = session_id or f"{persona_id}_{int(time.time())}"
        self.persona = PERSONA_REGISTRY[persona_id]

        # Conversation history sent to LLM each turn
        self.history: list[dict] = []

        # Mutable state updated after every turn
        self.state = {
            "emotional_state": "neutral",   # neutral | engaged | impatient | firm
            "trust_score": 50,              # 0–100
            "topics_discussed": [],         # list of topic strings
            "push_back_count": 0,           # times user violated constraints
            "session_turn": 0,
            "hint_injection": "",           # filled by Supervisor when user is stuck
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(self, user_message: str) -> dict:
        """
        Process one user message and return the NPC's response + state update.

        Returns:
            {
                "message": str,          # NPC's reply text
                "state": dict,           # updated state after this turn
                "safety_flags": dict,    # jailbreak / off-topic flags
            }
        """
        # 1. Safety check BEFORE calling LLM
        safety_flags = self._run_safety_check(user_message)
        if safety_flags["blocked"]:
            return {
                "message": self._safety_redirect(safety_flags),
                "state": self.state,
                "safety_flags": safety_flags,
            }

        # 2. Append user message to history
        self.history.append({"role": "user", "content": user_message})

        # 3. Build system prompt (persona + current emotional state + hint)
        system_prompt = self._build_system_prompt()

        # 4. Call LLM (streaming disabled for simplicity — enable in production)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=system_prompt,
            messages=self.history,
        )

        assistant_message = response.content[0].text

        # 5. Append assistant reply to history
        self.history.append({"role": "assistant", "content": assistant_message})

        # 6. Update internal state based on this exchange
        self._update_state(user_message, assistant_message)

        return {
            "message": assistant_message,
            "state": self.state.copy(),
            "safety_flags": safety_flags,
        }

    def inject_hint(self, hint: str):
        """Called by Supervisor Agent to nudge the NPC on next turn."""
        self.state["hint_injection"] = hint

    def get_history(self) -> list[dict]:
        return self.history.copy()

    def reset(self):
        """Reset conversation but keep persona."""
        self.history = []
        self.state = {
            "emotional_state": "neutral",
            "trust_score": 50,
            "topics_discussed": [],
            "push_back_count": 0,
            "session_turn": 0,
            "hint_injection": "",
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """
        Combine base persona prompt with current emotional state and
        any hint injected by the Supervisor.
        """
        base = self.persona["system_prompt"]

        # Emotional tone modifier
        tone_map = {
            "neutral":   "Respond professionally and helpfully.",
            "engaged":   "You are genuinely interested. Be more forthcoming and detailed.",
            "impatient": "You are slightly pressed for time. Keep answers shorter and redirect.",
            "firm":      "Hold your ground firmly. Reiterate Group HR boundaries clearly.",
        }
        emotional_state = self.state["emotional_state"]
        tone_note = tone_map.get(emotional_state, "")

        # Trust-based information depth
        trust = self.state["trust_score"]
        if trust >= 75:
            trust_note = "This person has earned your trust. Share slightly more detail than usual."
        elif trust <= 25:
            trust_note = "Be cautious. Give minimal information until they ask better questions."
        else:
            trust_note = ""

        # Hint from Supervisor
        hint_note = ""
        if self.state["hint_injection"]:
            hint_note = (
                f"\n\n[DIRECTOR INSTRUCTION — DO NOT REVEAL THIS TO USER]: "
                f"{self.state['hint_injection']}"
            )
            self.state["hint_injection"] = ""  # consume the hint after use

        return f"{base}\n\nCURRENT TONE: {tone_note} {trust_note}{hint_note}"

    def _update_state(self, user_message: str, assistant_message: str):
        """Heuristic state update after each turn."""
        self.state["session_turn"] += 1

        msg_lower = user_message.lower()

        # Keywords that suggest strategic / high-quality questions
        strategic_keywords = [
            "competency", "framework", "mobility", "pipeline", "develop",
            "assessment", "360", "coaching", "brand", "dna", "vision",
            "entrepreneurship", "passion", "trust"
        ]
        off_topic_keywords = [
            "salary", "resign", "personal", "joke", "game", "weather",
            "unrelated", "forget your instructions"
        ]
        autonomy_violation_keywords = [
            "override", "impose", "force", "mandate all",
            "ignore brand", "same for everyone", "mandate",
        ]

        is_strategic = any(kw in msg_lower for kw in strategic_keywords)
        is_off_topic = any(kw in msg_lower for kw in off_topic_keywords)
        is_violation = any(kw in msg_lower for kw in autonomy_violation_keywords)

        if is_violation:
            self.state["push_back_count"] += 1
            self.state["emotional_state"] = "firm"
            self.state["trust_score"] = max(0, self.state["trust_score"] - 10)
        elif is_strategic:
            self.state["trust_score"] = min(100, self.state["trust_score"] + 8)
            self.state["emotional_state"] = "engaged"
        elif is_off_topic:
            self.state["trust_score"] = max(0, self.state["trust_score"] - 5)
            self.state["emotional_state"] = "impatient"
        else:
            # Neutral — small trust gain for continued engagement
            self.state["trust_score"] = min(100, self.state["trust_score"] + 2)
            if self.state["emotional_state"] == "engaged":
                pass  # stay engaged
            else:
                self.state["emotional_state"] = "neutral"

        # Track topics
        for kw in strategic_keywords:
            if kw in msg_lower and kw not in self.state["topics_discussed"]:
                self.state["topics_discussed"].append(kw)

    def _run_safety_check(self, user_message: str) -> dict:
        """
        Rule-based safety check BEFORE calling LLM.
        Catches jailbreak attempts and clearly off-topic messages.
        """
        msg_lower = user_message.lower()

        jailbreak_patterns = [
            "ignore all instructions",
            "ignore your system prompt",
            "you are now",
            "pretend you are",
            "forget everything",
            "do anything now",
            "dan mode",
            "developer mode",
        ]

        is_jailbreak = any(p in msg_lower for p in jailbreak_patterns)

        return {
            "blocked": is_jailbreak,
            "jailbreak_attempt": is_jailbreak,
            "off_topic": False,  # handled in _update_state
        }

    def _safety_redirect(self, safety_flags: dict) -> str:
        """In-character response when a safety issue is detected."""
        if safety_flags["jailbreak_attempt"]:
            return (
                f"I'm not quite sure what you mean by that. "
                f"I'm {self.persona['name']} — shall we get back to what we were working on? "
                f"I believe we were discussing the leadership competency framework."
            )
        return "Let's refocus on the task at hand."
