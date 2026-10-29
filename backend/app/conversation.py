"""Conversation policy and optional OpenAI-compatible interviewer adapter.

The local policy works without credentials. Hosted generation is opt-in per
interview and never used for answer scoring.
"""
import json
import re
from urllib.request import Request, urlopen
from .config import settings


def hosted_json_completion(system_prompt: str, user_data: dict, temperature: float = 0.2) -> dict | None:
    """Call the configured OpenAI-compatible service and parse its JSON response."""
    api_key = settings.openai_api_key.strip()
    if not api_key:
        return None
    base_url = settings.openai_base_url.rstrip("/")
    context = [{"question": h.get("question", ""), "answer": h.get("answer", "")}
               for h in user_data.get("recent_history", [])[-6:]]
    payload = {
        "model": settings.openai_model,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({**user_data, "recent_history": context}, ensure_ascii=False)},
        ],
    }
    req = Request(f"{base_url}/chat/completions", data=json.dumps(payload).encode(),
                  headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                  method="POST")
    try:
        with urlopen(req, timeout=12) as response:
            data = json.loads(response.read())
        content = data["choices"][0]["message"]["content"]
        result = json.loads(content)
        return result if isinstance(result, dict) else None
    except Exception:
        # Provider errors are non-fatal; callers use their local fallback.
        return None


def _hosted_turn(question: dict, answer: str, history: list[dict]) -> dict | None:
    result = hosted_json_completion(
        "You are a concise, warm mock interviewer. Use only the supplied interview history. "
        "Return JSON with interviewer_response (one or two sentences), ask_follow_up (boolean), "
        "follow_up_question (string or empty). Ask at most one specific follow-up when clarification, "
        "evidence, or a missing detail would help. Otherwise move on. Never score personality, accent, "
        "honesty, confidence, or employability. Do not invent facts about the candidate.",
        {"current_question": question.get("prompt"), "candidate_answer": answer,
         "recent_history": history}, temperature=0.5,
    )
    if not result:
        return None
    response_text = str(result.get("interviewer_response", ""))[:500].strip()
    follow_up = str(result.get("follow_up_question", ""))[:500].strip()
    return {"interviewer_response": response_text or "Thanks for explaining that.",
            "follow_up_question": follow_up if result.get("ask_follow_up") and follow_up else None,
            "provider": "external_llm"}


def interviewer_turn(question: dict, answer: str, evaluation: dict,
                     history: list[dict], allow_external: bool = False) -> dict:
    """Create a conversational acknowledgement and, when useful, one follow-up."""
    if allow_external:
        hosted = _hosted_turn(question, answer, history)
        if hosted:
            return hosted

    cleaned = re.sub(r"\s+", " ", answer or "").strip()
    score = int(evaluation.get("score", 0))
    missing = evaluation.get("concepts_missing", [])
    if not cleaned:
        return {"interviewer_response": "I didn't catch an answer there. Let's move on, and you can revisit this topic later.",
                "follow_up_question": None, "provider": "local_policy"}

    words = cleaned.split()
    acknowledgment = "Thanks for walking me through that."
    if len(words) >= 5:
        excerpt = " ".join(words[:12]).rstrip(".,;:")
        acknowledgment = f"Thanks. I heard you say, ‘{excerpt}{'…' if len(words) > 12 else ''}.’"

    follow_up = None
    follow_up_count = sum(1 for item in history if item.get("is_follow_up"))
    if not question.get("is_follow_up") and follow_up_count < 2:
        if score < 45 and len(words) < 12:
            follow_up = "Could you add a little more detail about your approach and the reason behind it?"
        elif missing and score < 82:
            concept = str(missing[0])
            follow_up = f"You mentioned the main idea. How does {concept} fit into your explanation?"
        elif score >= 78:
            follow_up = "Can you give a concrete example of how you applied that, and what result you observed?"

    return {"interviewer_response": acknowledgment, "follow_up_question": follow_up,
            "provider": "local_policy"}
