"""Low-cost cross-chapter continuity candidates.

This is deliberately conservative: it creates review candidates from
explicit Korean rule/action patterns and never marks a contradiction as
author-confirmed. GPT remains responsible for the final explanation.
"""
from __future__ import annotations

import re
from collections import defaultdict


_RULE = re.compile(
    r"(?P<condition>[가-힣A-Za-z0-9][가-힣A-Za-z0-9 ]{0,24}?)(?:만|은|는)\s+"
    r"(?P<object>[가-힣A-Za-z0-9]{2,24})(?:을|를)?\s*"
    r"(?P<verb>사용|소유|출입|접근|착용|개방|꺼내|휘두르|열)[^.!?。\n]{0,50}?"
    r"(?:할 수 있다|가능하다|가능)"
)
_ACTION = re.compile(
    r"(?P<actor>[가-힣A-Za-z0-9]{1,20})\s+"
    r"(?P<condition>계약 없이|계약하지 않았지만|계약서에 서명하지 않았지만|서명하지 않은 채|서명하지 않았지만|허가 없이|허가받지 않았지만|조건 없이|자격 없이|자격이 없는데도)\s+"
    r"(?P<object>[가-힣A-Za-z0-9]{2,24})(?:을|를)?\s*"
    r"(?P<verb>사용|소유|출입|접근|착용|개방|꺼내|휘두르|열)"
)
_EXCEPTION = re.compile(r"예외|단,|다만|허용|허가받|조건을 충족|특별한 경우")


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value).strip()


def _object_particle(value: str) -> str:
    """Return the Korean object particle for a normalized noun."""
    noun = _compact(value)
    if not noun:
        return '을'
    code = ord(noun[-1])
    if 0xAC00 <= code <= 0xD7A3:
        return '을' if (code - 0xAC00) % 28 else '를'
    return '을'


def _object_name(value: str) -> str:
    """Normalize a regex capture that may include its object particle."""
    noun = _compact(value)
    return noun[:-1] if noun.endswith(('을', '를')) else noun


def _actor_name(value: str) -> str:
    noun = _compact(value)
    return noun[:-1] if noun.endswith(('은', '는')) else noun


def detect_rule_action_candidates(rows: list[dict], documents: list) -> list[dict]:
    """Find explicit rule/action pairs spanning chapters.

    Returned values use the same shape as persisted review issues. The
    evidence list always contains the exact source chunk IDs, and callers can
    merge these candidates with GPT output before publishing.
    """
    chapter_by_document = {document.id: document.chapter_index for document in documents}
    rules: list[tuple[int, int, re.Match[str], str]] = []
    actions: list[tuple[int, int, re.Match[str], str]] = []
    for row in rows:
        chapter = chapter_by_document.get(row['document_id'], 0)
        text = str(row.get('text') or '')
        for match in _RULE.finditer(text):
            rules.append((chapter, row['id'], match, text))
        for match in _ACTION.finditer(text):
            actions.append((chapter, row['id'], match, text))
    candidates: list[dict] = []
    for rule_chapter, rule_chunk, rule, rule_text in rules:
        rule_object = _object_name(rule.group('object'))
        for action_chapter, action_chunk, action, action_text in actions:
            if action_chapter <= rule_chapter or _object_name(action.group('object')) != rule_object:
                continue
            # An explicit exception in the intervening source means the pair
            # needs author review, but is not enough to call it a conflict.
            intervening = [
                str(row.get('text') or '') for row in rows
                if rule_chunk != row['id'] and action_chunk != row['id']
                and chapter_by_document.get(row['document_id'], 0) >= rule_chapter
                and chapter_by_document.get(row['document_id'], 0) <= action_chapter
            ]
            has_exception = any(_EXCEPTION.search(text) for text in intervening)
            title = '규칙과 행동의 전역 비교 후보'
            particle = _object_particle(rule_object)
            description = (
                f"{rule.group('condition').strip()}만 {rule_object}{particle} 사용할 수 있다는 규칙과 "
                f"{_actor_name(action.group('actor'))}가 {action.group('condition')} {rule_object}{particle} 사용했다는 행동을 "
                + ('예외 문구와 함께 확인해야 합니다.' if has_exception else '서로 다른 회차에서 확인했습니다.')
            )
            candidates.append({
                'title': title,
                'description': description,
                'severity': 'medium',
                'evidence_chunk_ids': sorted({rule_chunk, action_chunk}),
                'category': 'contradiction',
                'exception_review': has_exception,
            })
    # Same pair can be found in adjacent chunks; keep one candidate per
    # evidence set so the review panel does not become noisy.
    unique: dict[tuple[int, ...], dict] = {}
    for candidate in candidates:
        unique.setdefault(tuple(candidate['evidence_chunk_ids']), candidate)
    return list(unique.values())
