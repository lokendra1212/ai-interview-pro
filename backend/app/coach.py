"""Evidence-grounded learning coach for a single authenticated candidate."""
from collections import defaultdict, Counter
from datetime import datetime, timezone
from typing import Any

from .config import settings
from .conversation import hosted_json_completion
from .questions import BANK


def _score(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    value = float(value)
    return value if 0 <= value <= 100 else None


def _text(value: Any, limit: int = 500) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _topic_analysis(sessions: list[Any]) -> tuple[list[dict], list[dict], int]:
    topics: dict[str, list[dict]] = defaultdict(list)
    scored_answers = 0
    for session in sessions:
        if not isinstance(session.answers, list):
            continue
        for answer in session.answers:
            if not isinstance(answer, dict):
                continue
            result = answer.get("result")
            question = answer.get("question")
            if not isinstance(result, dict) or not isinstance(question, dict):
                continue
            score = _score(result.get("score"))
            topic = _text(question.get("topic") or question.get("skill"), 100)
            if score is None or not topic:
                continue
            missing = result.get("concepts_missing")
            missing = [_text(item, 80) for item in missing if isinstance(item, str)] if isinstance(missing, list) else []
            breakdown = result.get("breakdown") if isinstance(result.get("breakdown"), dict) else {}
            breakdown = {str(key): round(value) for key, value in breakdown.items() if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100}
            topics[topic.casefold()].append({
                "topic": topic,
                "score": score,
                "question": _text(question.get("prompt"), 400),
                "feedback": _text(result.get("feedback"), 400),
                "missing": missing,
                "breakdown": breakdown,
                "answer": _text(answer.get("answer"), 500),
                "created_at": session.created_at,
            })
            scored_answers += 1

    analysis = []
    for answers in topics.values():
        ordered = sorted(answers, key=lambda item: item["created_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        average = round(sum(item["score"] for item in answers) / len(answers))
        below_target = sum(item["score"] < 70 for item in answers)
        missing_counts = Counter(concept for item in answers for concept in item["missing"])
        priority = "high" if average < 45 or (average < 60 and below_target >= 2) else "medium" if average < 70 else "low"
        low_answers = [item for item in ordered if item["score"] < 70]
        evidence_items = low_answers[:2] or ordered[:1]
        previously_seen = {item["question"].casefold() for item in ordered if item["question"]}
        available_questions = [item["prompt"] for item in BANK if item.get("topic", "").casefold() == ordered[0]["topic"].casefold() and item.get("prompt", "").casefold() not in previously_seen]
        practice_questions = available_questions[:3] or [item["question"] for item in evidence_items if item["question"]][:3]
        evidence = [{
            "question": item["question"],
            "score": round(item["score"]),
            "missing_concepts": item["missing"][:4],
            "breakdown": item["breakdown"],
            "feedback": item["feedback"],
        } for item in evidence_items]
        reason = f"Measured average {average}/100 across {len(answers)} scored answer{'s' if len(answers) != 1 else ''}; {below_target} scored below 70."
        common_missing = [concept for concept, _ in missing_counts.most_common(4)]
        if common_missing:
            reason += " Repeated gaps: " + ", ".join(common_missing) + "."
        analysis.append({
            "topic": ordered[0]["topic"],
            "measured_score": average,
            "score_type": "measured_average",
            "attempts": len(answers),
            "below_target": below_target,
            "priority": priority,
            "reason": reason,
            "common_gaps": common_missing,
            "evidence": evidence,
            "practice_questions": practice_questions,
            "recent_history": [{"question": item["question"], "answer": item["answer"]} for item in ordered[:3]],
        })
    order = {"high": 0, "medium": 1, "low": 2}
    analysis.sort(key=lambda item: (order[item["priority"]], item["measured_score"], -item["attempts"], item["topic"].casefold()))
    return analysis, list(topics.values()), scored_answers


def _local_plan(topic: dict | None) -> tuple[str, list[dict]]:
    if topic is None:
        return "Build a baseline from three short interview answers.", [{
            "title": "Take a 3-question diagnostic",
            "minutes": 15,
            "action": "Answer a short mixed-topic technical set. This gives the coach measured starting scores without assuming a weakness.",
            "objective": "Establish a first measured baseline across interview topics.",
            "practice": "Complete three focused interview questions in the app.",
            "success_criteria": "Submit all three answers; each answer receives a saved score and feedback.",
            "after": "Review the answer feedback and return for a topic-specific plan.",
        }]

    topic_name = topic["topic"]
    score = topic["measured_score"]
    target_score = min(95, score + 10) if score < 70 else min(95, max(85, score + 5))
    gaps = topic["common_gaps"]
    gap_text = ", ".join(gaps[:3]) if gaps else "the concepts flagged in your saved answer feedback"
    objective = f"Raise your measured {topic_name} performance from {score}/100 toward {target_score}+." if score < 70 else f"Extend your measured {topic_name} performance from {score}/100 toward {target_score} with more advanced examples."
    return objective, [
        {
            "title": f"Review your {topic_name} feedback",
            "minutes": 15,
            "action": f"Open your saved answers for {topic_name} and revisit {gap_text}.",
            "objective": "Explain the key concepts accurately before adding detail.",
            "practice": "Use the question and feedback shown in your recent answer evidence.",
            "success_criteria": "Explain each flagged concept in your own words and connect it to the question.",
            "after": "Move on to a focused practice set and use the rubric feedback to check your explanation.",
        },
        {
            "title": f"Practice {topic_name} with three questions",
            "minutes": 20,
            "action": f"Complete a focused {topic_name} session, then compare each score with your current measured average.",
            "objective": "Apply the reviewed concepts in concise, structured interview answers.",
            "practice": "Start a new 3-question practice session for this topic.",
            "success_criteria": f"Reach at least {target_score}/100 average across three scored answers.",
            "after": "Review any remaining missed concepts; the coach will update from the newly saved answers.",
        },
    ]


def _enhance_plan(plan: list[dict], topic: dict, role: str | None, resume_skills: list[str]) -> tuple[list[dict], bool]:
    payload = {
        "focus_topic": topic["topic"],
        "target_role": role,
        "resume_skills": resume_skills,
        "measured_score": topic["measured_score"],
        "attempts": topic["attempts"],
        "repeated_gaps": topic["common_gaps"],
        "evidence": [{"question": item["question"], "score": item["score"], "breakdown": item["breakdown"], "missing_concepts": item["missing_concepts"], "feedback": item["feedback"]} for item in topic["evidence"]],
        "recent_history": topic["recent_history"],
        "local_plan": plan,
    }
    result = hosted_json_completion(
        "You are a practical interview study coach. Build an achievable plan using only the supplied evidence. "
        "The measured score, focus topic, and evidence are fixed facts: do not change, re-label, or invent them. "
        "Return a JSON object with objective and steps. Each step must have title, minutes (integer 5-45), "
        "action, practice, success_criteria, and after. Keep the plan to at most 3 steps and about 60 minutes total. "
        "Do not invent candidate history, scores, learning resources, or claims about their performance. "
        "You may improve teaching explanations and practice prompts, but only within the provided focus topic. "
        "Do not assess employability, personality, accent, or confidence.",
        payload,
        temperature=0.2,
    )
    steps = result.get("steps") if isinstance(result, dict) else None
    if not isinstance(steps, list) or not steps:
        return plan, False
    cleaned = []
    for step in steps[:3]:
        if not isinstance(step, dict):
            continue
        title = _text(step.get("title"), 100)
        if not title:
            continue
        minutes = step.get("minutes")
        minutes = max(5, min(45, int(minutes))) if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) else 15
        cleaned.append({
            "title": title,
            "minutes": minutes,
            "action": _text(step.get("action"), 500) or plan[0]["action"],
            "objective": _text(result.get("objective"), 300) or plan[0]["objective"],
            "practice": _text(step.get("practice"), 400) or plan[0]["practice"],
            "success_criteria": _text(step.get("success_criteria"), 300) or plan[0]["success_criteria"],
            "after": _text(step.get("after"), 300) or plan[0]["after"],
        })
    return (cleaned, True) if cleaned else (plan, False)


def build_coach_plan(sessions: list[Any], resume: Any | None, allow_external_ai: bool = False) -> dict:
    completed = [session for session in sessions if session.status == "completed" and isinstance(session.report, dict)]
    topics, _, answers_analyzed = _topic_analysis(completed)
    has_baseline = answers_analyzed >= 3
    focus = topics[0] if has_baseline and topics else None
    resume_skills = resume.skills if resume and isinstance(resume.skills, list) else []
    unique_resume_skills = list(dict.fromkeys(_text(skill, 80) for skill in resume_skills if _text(skill, 80)))[:30]
    if focus and any(focus["topic"].casefold() == skill.casefold() for skill in unique_resume_skills):
        focus["reason"] += " This topic also appears in your saved resume skills."
    plan_objective, plan = _local_plan(focus)
    external_available = bool(settings.openai_api_key.strip())
    mode = "evidence_based_local"
    if focus and allow_external_ai and external_available:
        plan, external_used = _enhance_plan(plan, focus, completed[0].role if completed else None, unique_resume_skills)
        if external_used:
            mode = "external_ai"
    priority_topics = [
        {key: value for key, value in topic.items() if key != "recent_history"}
        for topic in topics[:5]
    ] if has_baseline else []
    roles = [session.role.strip() for session in completed if isinstance(session.role, str) and session.role.strip()]
    latest_role = roles[0] if roles else None
    if not has_baseline:
        summary = "There are not yet three scored answers to identify a reliable topic weakness. Start a short diagnostic to establish measured scores."
    else:
        summary = f"Your strongest opportunity is {focus['topic']}: {focus['reason']}"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "has_baseline": has_baseline,
        "sessions_analyzed": len(completed),
        "answers_analyzed": answers_analyzed,
        "target_role": latest_role,
        "resume_skills": unique_resume_skills,
        "external_ai_available": external_available,
        "coach_mode": mode,
        "focus_topic": focus["topic"] if focus else None,
        "headline": f"Next focus: {focus['topic']}" if focus else "Start with a short diagnostic",
        "summary": summary,
        "weak_topics": priority_topics,
        "objective": plan_objective,
        "plan": plan,
    }
