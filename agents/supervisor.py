"""
Supervisor Agent — The "Director" Layer
Invisible to the user. Monitors the conversation and keeps the simulation on track.
"""

import os
from anthropic import Anthropic

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


class SupervisorAgent:
    """
    Monitors all NPC conversations in a session.
    Detects when user is stuck and injects subtle hints into the NPC.
    Never communicates directly with the user.
    """

    STUCK_THRESHOLD = 6       # score out of 10
    PROGRESS_THRESHOLD = 30   # minimum progress score before checking stuck

    def __init__(self, simulation_id: str = "gucci_hrm"):
        self.simulation_id = simulation_id
        self.turn_count = 0
        self.hints_given = 0
        self.progress_log = []

    # ------------------------------------------------------------------
    # Main entry: call after every user message
    # ------------------------------------------------------------------

    def evaluate(
        self,
        conversation_history: list[dict],
        current_module: str,
        npc_agent,  # NPCAgent instance — will call inject_hint() if needed
    ) -> dict:
        """
        Evaluate conversation health and inject hint if necessary.

        Returns:
            {
                "stuck": bool,
                "stuck_score": int,
                "progress_score": int,
                "action": str,   # "none" | "hint_injected"
                "hint": str,
            }
        """
        self.turn_count += 1

        # Only check after 3+ turns (not enough data before that)
        if len(conversation_history) < 6:
            return self._result(False, 0, 0, "none", "")

        stuck_analysis = self._detect_stuck(conversation_history)
        progress_score = self._estimate_progress(conversation_history, current_module)

        if stuck_analysis["stuck"] and progress_score < 80:
            hint = self._generate_hint(
                conversation_history, current_module, stuck_analysis
            )
            npc_agent.inject_hint(hint)
            self.hints_given += 1
            return self._result(True, stuck_analysis["score"], progress_score, "hint_injected", hint)

        return self._result(False, stuck_analysis["score"], progress_score, "none", "")

    # ------------------------------------------------------------------
    # Stuck detection (rule-based, fast — no LLM call)
    # ------------------------------------------------------------------

    def _detect_stuck(self, history: list[dict]) -> dict:
        """
        Detect repetition in user messages using simple keyword overlap.
        Fast, no LLM needed.
        """
        user_messages = [
            m["content"].lower()
            for m in history[-8:]
            if m["role"] == "user"
        ]

        if len(user_messages) < 3:
            return {"stuck": False, "score": 0}

        # Count overlapping words across recent messages
        word_sets = [set(msg.split()) for msg in user_messages]
        overlap_scores = []
        for i in range(len(word_sets) - 1):
            a, b = word_sets[i], word_sets[i + 1]
            if not a or not b:
                continue
            jaccard = len(a & b) / len(a | b)
            overlap_scores.append(jaccard)

        avg_overlap = sum(overlap_scores) / len(overlap_scores) if overlap_scores else 0
        stuck_score = round(avg_overlap * 10)

        return {
            "stuck": stuck_score >= self.STUCK_THRESHOLD,
            "score": stuck_score,
        }

    # ------------------------------------------------------------------
    # Progress estimation (LLM call — only when stuck is detected)
    # ------------------------------------------------------------------

    def _estimate_progress(self, history: list[dict], module: str) -> int:
        """
        Quick LLM call to estimate how much of the module the user has covered.
        Returns 0–100.
        """
        module_goals = {
            "module_1": (
                "Write problem statement, define Group DNA, "
                "build competency model with 4 themes x 3 levels"
            ),
            "module_2": (
                "Design 360° feedback instrument, participant journey, "
                "coaching program, vendor plan"
            ),
            "module_3": (
                "Build train-the-trainer plan, define change risks, "
                "construct KPI measurement dashboard"
            ),
        }

        goals = module_goals.get(module, "Complete the simulation tasks")
        recent = history[-6:]
        conversation_snippet = "\n".join(
            f"{m['role'].upper()}: {m['content'][:200]}" for m in recent
        )

        prompt = (
            f"Module goal: {goals}\n\n"
            f"Recent conversation:\n{conversation_snippet}\n\n"
            f"On a scale of 0 to 100, how much progress has the user made "
            f"toward the module goal? Reply with only a number."
        )

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",  # cheap + fast for this check
                max_tokens=10,
                messages=[{"role": "user", "content": prompt}],
            )
            score_text = response.content[0].text.strip()
            return int("".join(filter(str.isdigit, score_text)) or "50")
        except Exception:
            return 50  # default if call fails

    # ------------------------------------------------------------------
    # Hint generation
    # ------------------------------------------------------------------

    def _generate_hint(
        self, history: list[dict], module: str, stuck_analysis: dict
    ) -> str:
        """
        Generate a context-aware hint for the NPC to deliver naturally.
        Uses LLM for quality, but short and targeted.
        """
        # Fallback rule-based hints (fast, no LLM)
        rule_hints = {
            "module_1": (
                "The user seems to be going in circles. Gently redirect: "
                "ask them to summarize what they know so far about the 4 competency themes, "
                "then suggest picking one theme and defining its 3 behavioral levels first."
            ),
            "module_2": (
                "The user appears stuck on the 360° design. Offer a starting point: "
                "suggest they define the rater groups first (manager, peer, direct report, self), "
                "then move to writing 2-3 sample questions per competency theme."
            ),
            "module_3": (
                "The user seems unsure about rollout. Scaffold: 'Have you thought about "
                "piloting with one brand in one region before scaling? Which brand and "
                "region would be your lowest-risk starting point?'"
            ),
        }
        return rule_hints.get(
            module,
            "The user needs a nudge. Ask: 'What is your biggest blocker right now?'"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _result(self, stuck, stuck_score, progress, action, hint) -> dict:
        return {
            "stuck": stuck,
            "stuck_score": stuck_score,
            "progress_score": progress,
            "action": action,
            "hint": hint,
        }
