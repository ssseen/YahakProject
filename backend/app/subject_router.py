"""
과목 판정 — Pinecone 무필터 검색 결과(matches)로 영어/수학/국사과 중 어느
브랜치인지 다수결로 정하고, 라틴 문자 비율/수식 기호 밀도로 가드·폴백을 건다.

임계값(THRESHOLD=0.25)은 scripts/subject_eval.py의 leave-one-out 검증 결과로
확정됨 (2026-08-25): 0.25/0.30/0.35/0.40/0.45 중 0.25가 정확도(98.66%)·영어
오분류(35건)·agreement 안정성 모두에서 가장 좋았음. 임계값을 낮출수록 다수결에
참여하는 이웃 수가 늘어 노이즈가 평균화되는 방향이라, 5개 후보 중 최저값이 최선이었음.
"""
import re
from collections import Counter
from dataclasses import dataclass

THRESHOLD = 0.25
SIMILAR_THRESHOLD = 0.70

BRANCH_OF = {
    "영어": "영어", "수학": "수학",
    "국어": "국사과", "사회": "국사과", "과학": "국사과",
    "한국사": "국사과", "도덕": "국사과",
}

_MATH_PATTERN = re.compile(r'[=+×÷√∫∑≤≥∠△∽]|\d+/\d+|\^\d|\bx\b')


@dataclass
class BranchResult:
    branch: str          # "영어" | "수학" | "국사과"
    subject_hint: str | None  # 다수결 1위의 원본 subject
    agreement: float
    vote_count: int
    guard: str | None    # "latin_override" | "math_fallback" | None


def _match_score(m):
    # .score 프로퍼티 사용. _score 아님 (기존 버그 재발 방지).
    return getattr(m, "score", None)


def _match_subject(m):
    fields = getattr(m, "fields", None) or {}
    if isinstance(fields, dict):
        return fields.get("subject")
    return getattr(fields, "subject", None)


def _match_id(m):
    return getattr(m, "id", None)


def latin_ratio(t: str) -> float:
    latin = sum(1 for c in t if c.isascii() and c.isalpha())
    hangul = sum(1 for c in t if '가' <= c <= '힣')
    total = latin + hangul
    return latin / total if total else 0.0


def math_hits(t: str) -> int:
    return len(_MATH_PATTERN.findall(t))


def decide_branch(matches, query_text: str) -> BranchResult:
    votes: list[str] = []
    raw_subject_votes: Counter = Counter()

    for m in matches:
        score = _match_score(m)
        subj = _match_subject(m)
        # category_large는 쓰지 않는다 — "문법"이 국어/영어 양쪽에 존재해 구분 불가.
        if score is not None and score >= THRESHOLD and subj in BRANCH_OF:
            votes.append(BRANCH_OF[subj])
            raw_subject_votes[subj] += 1

    if votes:
        vc = Counter(votes)
        branch, n = vc.most_common(1)[0]
        agreement = n / len(votes)
        vote_count = len(votes)
    else:
        branch = "국사과"
        agreement = 0.0
        vote_count = 0

    subject_hint = raw_subject_votes.most_common(1)[0][0] if raw_subject_votes else None

    guard = None
    if latin_ratio(query_text) > 0.6 and branch != "영어":
        branch = "영어"
        guard = "latin_override"
    elif len(query_text.strip()) < 30 or agreement < 0.5:
        branch = "수학" if math_hits(query_text) >= 3 else "국사과"
        guard = "math_fallback"

    return BranchResult(
        branch=branch,
        subject_hint=subject_hint,
        agreement=agreement,
        vote_count=vote_count,
        guard=guard,
    )


def select_similar(matches, branch: str, exclude_id=None) -> list:
    out = []
    for m in matches:
        if exclude_id is not None and _match_id(m) == exclude_id:
            continue
        subj = _match_subject(m)
        if subj not in BRANCH_OF or BRANCH_OF[subj] != branch:
            continue
        score = _match_score(m)
        if score is None or score < SIMILAR_THRESHOLD:
            continue
        out.append(m)
        if len(out) >= 3:
            break
    return out
