"""Build a per-attempt exam form: validate the bank and shuffle option letters."""

from __future__ import annotations

import random
import re
from collections import Counter

from django.conf import settings

from .models import LETTERS, Question

MAX_SHUFFLE_TRIES = 50

# Short form domain allocation (30 items total)
SHORT_FORM_DOMAIN_COUNTS = {
    "D1": 8,  # 27% of 30 ≈ 8.1
    "D2": 5,  # 18% of 30 ≈ 5.4
    "D3": 6,  # 20% of 30 = 6
    "D4": 6,  # 20% of 30 = 6
    "D5": 5,  # 15% of 30 ≈ 4.5
}


class BankError(Exception):
    """The loaded question bank cannot be used to start an exam."""


def validate_bank(questions: list[Question]) -> list[str]:
    errors: list[str] = []
    if not questions:
        return ["No questions loaded. Run: python manage.py load_questions"]

    numbers = [q.number for q in questions]
    if len(numbers) != len(set(numbers)):
        errors.append("Duplicate question numbers in the bank.")

    for q in questions:
        texts = [text.strip() for _, text in q.options()]
        if any(not text for text in texts):
            errors.append(f"Q{q.number} has an empty option.")
        if len(set(texts)) < 4:
            errors.append(f"Q{q.number} has duplicate option text.")
        if not q.correct_set or not q.correct_set <= set(LETTERS):
            errors.append(f"Q{q.number} has an invalid correct-answer set.")
        if q.qtype == Question.MULTI:
            if len(q.correct_set) < 2:
                errors.append(f"Q{q.number} is multiple-response but has fewer than 2 correct options.")
        elif len(q.correct_set) != 1:
            errors.append(f"Q{q.number} is single-choice but does not have exactly 1 correct option.")
        if not (q.explanation or "").strip():
            errors.append(f"Q{q.number} is missing an explanation.")
    return errors


def _display_letter_for(q: Question, slots: list[str], original: str) -> str:
    return LETTERS[slots.index(original)]


def presentation_is_well_mixed(questions: list[Question], presentation: dict) -> bool:
    """Reject a shuffle that still puts almost every correct answer on A."""
    singles = [q for q in questions if q.qtype != Question.MULTI]
    if len(singles) < 4:
        return True

    letters = []
    for q in singles:
        slots = presentation[str(q.number)]["slots"]
        orig = next(iter(q.correct_set))
        letters.append(_display_letter_for(q, slots, orig))

    counts = Counter(letters)
    n = len(letters)
    if len(counts) < 3:
        return False
    # After a fair shuffle each letter is ~25%. Reject if any letter exceeds 50%.
    if max(counts.values()) > n * 0.5:
        return False
    return True


def shuffle_presentation(questions: list[Question], rng=None) -> dict:
    rng = rng or random
    presentation = {}
    for q in questions:
        slots = LETTERS[:]
        rng.shuffle(slots)
        presentation[str(q.number)] = {"slots": slots}
    return presentation


def sample_short_form(all_questions: list[Question], rng=None) -> list[Question]:
    """Sample 30 questions from the bank, maintaining domain weights."""
    rng = rng or random
    by_domain = {}
    for q in all_questions:
        by_domain.setdefault(q.domain, []).append(q)
    
    sampled = []
    for domain, count in SHORT_FORM_DOMAIN_COUNTS.items():
        available = by_domain.get(domain, [])
        if len(available) < count:
            raise BankError(f"Not enough questions in {domain}: need {count}, have {len(available)}")
        sampled.extend(rng.sample(available, count))
    
    return sampled


def build_validated_presentation(questions: list[Question], rng=None) -> dict:
    errors = validate_bank(questions)
    if errors:
        raise BankError(" ".join(errors))

    last = None
    for _ in range(MAX_SHUFFLE_TRIES):
        last = shuffle_presentation(questions, rng=rng)
        if presentation_is_well_mixed(questions, last):
            return last
    return last


def remap_explanation(text: str, slots: list[str]) -> str:
    """Rewrite A/B/C/D mentions in an explanation to match shuffled display letters."""
    orig_to_disp = {orig: LETTERS[i] for i, orig in enumerate(slots)}
    out = text
    for orig, disp in orig_to_disp.items():
        out = re.sub(rf"\b{orig}\b", f"\x00{disp}\x00", out)
    for disp in LETTERS:
        out = out.replace(f"\x00{disp}\x00", disp)
    return out
