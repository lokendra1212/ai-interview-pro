import re
from collections import Counter

WEIGHTS = {"correctness": 0.35, "relevance": 0.25, "completeness": 0.20, "clarity": 0.20}
FILLERS = {"um", "uh", "like", "basically", "actually", "you know"}

def evaluate(question: dict, answer: str) -> dict:
    text = re.sub(r"\s+", " ", answer or "").strip()
    if not text:
        return {"score": 0, "breakdown": {"correctness":0,"relevance":0,"completeness":0,"clarity":0}, "concepts_covered":[], "concepts_missing":question.get("concepts", []), "feedback":"No answer was provided. Try a short response that addresses the key parts of the question.", "semantic_method":"unavailable for empty answer"}
    low = text.lower()
    concepts = question.get("concepts", [])
    covered = [c for c in concepts if c.lower() in low]
    completeness = round(100 * len(covered) / max(1, len(concepts)))
    answer_words = re.findall(r"[\w+#.-]+", low)
    prompt_terms = [w for w in re.findall(r"[\w+#.-]+", question.get("prompt", "").lower()) if len(w) > 4 and w not in {"about", "would", "could", "explain", "describe"}]
    overlap = len(set(answer_words) & set(prompt_terms)) / max(1, min(6, len(set(prompt_terms))))
    lexical_relevance = min(100, round(35 + overlap * 65)) if len(answer_words) >= 3 else 15
    semantic_method = "token overlap fallback"
    tfidf_relevance = 0
    reference = question.get("reference", "")
    if len(answer_words) >= 3 and reference:
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
            matrix = TfidfVectorizer(ngram_range=(1, 2), stop_words="english").fit_transform([question.get("prompt", ""), reference, text])
            tfidf_relevance = round(float(max(cosine_similarity(matrix[2], matrix[0])[0, 0], cosine_similarity(matrix[2], matrix[1])[0, 0])) * 100)
            semantic_method = "scikit-learn TF-IDF cosine lexical similarity; not proof of correctness"
        except (ImportError, ValueError):
            semantic_method = "token overlap fallback; TF-IDF unavailable"
    relevance = round(lexical_relevance * .5 + tfidf_relevance * .5) if semantic_method.startswith("scikit-learn") else lexical_relevance
    clarity = min(100, 35 + min(35, len(answer_words)) + (15 if any(mark in text for mark in ".,;:") else 0) + (15 if len(set(answer_words)) / max(1,len(answer_words)) > .55 else 0))
    # A transparent concept checklist anchors correctness. Similarity is only a lexical proxy.
    correctness = min(100, round(20 + completeness * .8))
    breakdown = {"correctness":correctness,"relevance":relevance,"completeness":completeness,"clarity":clarity}
    score = round(sum(breakdown[k] * WEIGHTS[k] for k in WEIGHTS))
    missing = [c for c in concepts if c not in covered]
    advice = []
    if missing: advice.append("Cover these ideas: " + ", ".join(missing) + ".")
    if len(answer_words) < 20: advice.append("Add a specific example or explain why your approach works.")
    if not advice: advice.append("Good coverage. Strengthen the response with a concrete example and result.")
    return {"score":score,"breakdown":breakdown,"weights":WEIGHTS,"concepts_covered":covered,"concepts_missing":missing,"feedback":" ".join(advice),"semantic_method":semantic_method}

def communication_metrics(text: str, duration_seconds: float | None = None):
    words = re.findall(r"\b[\w']+\b", text.lower())
    counts = Counter(words)
    fillers = sum(1 for w in words if w in {"um","uh","like","basically","actually"})
    repeated = sum(n-1 for w,n in counts.items() if n > 1 and len(w) > 3)
    duration = max(1, duration_seconds or (len(words) / 2.4 if words else 1))
    return {"word_count":len(words),"duration_seconds":round(duration,1) if duration_seconds else None,"words_per_minute":round(len(words)/duration*60) if duration_seconds else None,"filler_count":fillers,"repeated_word_estimate":repeated,"pause_analysis":"unavailable: browser transcript has no reliable word timestamps"}
