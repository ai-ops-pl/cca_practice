import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

LETTERS = ["A", "B", "C", "D"]
DEFAULT_BANK = "questions"


def bank_label(bank):
    return bank.replace("_", " ").title()


class Question(models.Model):
    SINGLE = "single"
    MULTI = "multi"
    TYPE_CHOICES = [(SINGLE, "Multiple choice"), (MULTI, "Multiple response")]

    bank = models.CharField(max_length=64, default=DEFAULT_BANK, db_index=True)
    number = models.PositiveIntegerField()
    scenario = models.CharField(max_length=120)
    domain = models.CharField(max_length=4)
    qtype = models.CharField(max_length=10, choices=TYPE_CHOICES, default=SINGLE)
    text = models.TextField()
    option_a = models.TextField()
    option_b = models.TextField()
    option_c = models.TextField()
    option_d = models.TextField()
    correct = models.CharField(max_length=10, help_text="Comma-separated letters, e.g. 'A' or 'A,B'")
    explanation = models.TextField()

    class Meta:
        ordering = ["bank", "number"]
        constraints = [
            models.UniqueConstraint(fields=["bank", "number"], name="unique_bank_number"),
        ]

    def __str__(self):
        return f"Q{self.number} [{self.domain}] {self.text[:60]}"

    @property
    def correct_set(self):
        return {c.strip().upper() for c in self.correct.split(",") if c.strip()}

    @property
    def select_count(self):
        return len(self.correct_set)

    @property
    def domain_name(self):
        return settings.EXAM["DOMAINS"][self.domain]["name"]

    def options(self):
        return [
            ("A", self.option_a),
            ("B", self.option_b),
            ("C", self.option_c),
            ("D", self.option_d),
        ]


class Attempt(models.Model):
    FULL = "full"
    SHORT = "short"
    FORM_CHOICES = [(FULL, "Full exam"), (SHORT, "Short practice")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.CharField(max_length=120, blank=True)
    bank = models.CharField(max_length=64, default=DEFAULT_BANK)
    started_at = models.DateTimeField(default=timezone.now)
    submitted_at = models.DateTimeField(null=True, blank=True)
    form_type = models.CharField(max_length=10, choices=FORM_CHOICES, default=FULL)
    duration_minutes = models.PositiveIntegerField(default=120)
    order = models.JSONField(default=list)  # list of Question.number, in delivery order
    answers = models.JSONField(default=dict)  # {"<question number>": ["A", "C"]} display letters
    flagged = models.JSONField(default=list)  # list of question numbers
    presentation = models.JSONField(default=dict)  # {"<number>": {"slots": ["C","A","D","B"]}}
    paused_at = models.DateTimeField(null=True, blank=True)
    pause_seconds = models.PositiveIntegerField(default=0)
    scaled_score = models.PositiveIntegerField(null=True, blank=True)
    raw_correct = models.PositiveIntegerField(null=True, blank=True)
    passed = models.BooleanField(null=True, blank=True)
    auto_submitted = models.BooleanField(default=False)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        state = "submitted" if self.submitted_at else "in progress"
        return f"Attempt {str(self.id)[:8]} ({state})"

    @property
    def bank_label(self):
        return bank_label(self.bank)

    # -- timing ------------------------------------------------------------
    @property
    def is_paused(self):
        return self.submitted_at is None and self.paused_at is not None

    def _completed_pause_seconds(self):
        extra = self.pause_seconds or 0
        if self.is_paused:
            extra += max(0, int((timezone.now() - self.paused_at).total_seconds()))
        return extra

    @property
    def deadline(self):
        return self.started_at + timedelta(
            minutes=self.duration_minutes, seconds=self.pause_seconds or 0
        )

    @property
    def seconds_remaining(self):
        if self.submitted_at:
            return 0
        if self.is_paused:
            frozen_deadline = self.started_at + timedelta(
                minutes=self.duration_minutes, seconds=self.pause_seconds or 0
            )
            return max(0, int((frozen_deadline - self.paused_at).total_seconds()))
        return max(0, int((self.deadline - timezone.now()).total_seconds()))

    @property
    def expired(self):
        if self.submitted_at is not None or self.is_paused:
            return False
        return timezone.now() >= self.deadline

    def pause(self):
        if self.submitted_at or self.is_paused:
            return False
        self.paused_at = timezone.now()
        self.save(update_fields=["paused_at"])
        return True

    def resume(self):
        if self.submitted_at or not self.is_paused:
            return False
        extra = max(0, int((timezone.now() - self.paused_at).total_seconds()))
        self.pause_seconds = (self.pause_seconds or 0) + extra
        self.paused_at = None
        self.save(update_fields=["pause_seconds", "paused_at"])
        return True

    @property
    def time_used_display(self):
        if self.submitted_at:
            end = self.submitted_at
        elif self.is_paused:
            end = self.paused_at
        else:
            end = timezone.now()
        total = int((end - self.started_at).total_seconds()) - (self.pause_seconds or 0)
        total = max(0, total)
        return f"{total // 3600:d}h {(total % 3600) // 60:02d}m {total % 60:02d}s"

    # -- questions / shuffled options --------------------------------------
    def questions(self):
        qs = {q.number: q for q in Question.objects.filter(bank=self.bank, number__in=self.order)}
        return [qs[n] for n in self.order if n in qs]

    def slots_for(self, q):
        data = (self.presentation or {}).get(str(q.number)) or {}
        slots = data.get("slots")
        if not slots or set(slots) != set(LETTERS):
            return LETTERS[:]
        return list(slots)

    def display_options(self, q):
        original = dict(q.options())
        return [(LETTERS[i], original[orig]) for i, orig in enumerate(self.slots_for(q))]

    def display_correct(self, q):
        orig_to_disp = {orig: LETTERS[i] for i, orig in enumerate(self.slots_for(q))}
        return {orig_to_disp[c] for c in q.correct_set if c in orig_to_disp}

    def display_explanation(self, q):
        from .formbuild import remap_explanation

        return remap_explanation(q.explanation, self.slots_for(q))

    @property
    def answered_count(self):
        return len([n for n, v in self.answers.items() if v])

    # -- scoring -----------------------------------------------------------
    def score(self):
        """Grade the attempt. Multiple-response items are all-or-nothing."""
        questions = self.questions()
        total = len(questions) or 1
        correct = 0
        per_domain = {}
        for q in questions:
            given = set(self.answers.get(str(q.number), []))
            is_right = given == self.display_correct(q)
            correct += 1 if is_right else 0
            bucket = per_domain.setdefault(q.domain, {"correct": 0, "total": 0})
            bucket["total"] += 1
            bucket["correct"] += 1 if is_right else 0

        raw = correct / total
        cfg = settings.EXAM
        cut_raw, cut = cfg["CUT_RAW"], cfg["CUT_SCORE"]
        lo, hi = cfg["SCALED_MIN"], cfg["SCALED_MAX"]
        if raw <= cut_raw:
            scaled = lo + (raw / cut_raw) * (cut - lo)
        else:
            scaled = cut + ((raw - cut_raw) / (1 - cut_raw)) * (hi - cut)
        scaled = int(round(min(hi, max(lo, scaled))))

        self.raw_correct = correct
        self.scaled_score = scaled
        self.passed = scaled >= cut
        return {"correct": correct, "total": total, "raw": raw, "scaled": scaled, "domains": per_domain}

    def domain_breakdown(self):
        rows = []
        per_domain = {}
        for q in self.questions():
            given = set(self.answers.get(str(q.number), []))
            bucket = per_domain.setdefault(q.domain, {"correct": 0, "total": 0})
            bucket["total"] += 1
            if given == self.display_correct(q):
                bucket["correct"] += 1
        for key, meta in settings.EXAM["DOMAINS"].items():
            b = per_domain.get(key, {"correct": 0, "total": 0})
            pct = round(100 * b["correct"] / b["total"]) if b["total"] else 0
            rows.append(
                {
                    "key": key,
                    "name": meta["name"],
                    "weight": meta["weight"],
                    "correct": b["correct"],
                    "total": b["total"],
                    "percent": pct,
                }
            )
        return rows

    def review_rows(self):
        rows = []
        for idx, q in enumerate(self.questions(), start=1):
            given = sorted(self.answers.get(str(q.number), []))
            correct = self.display_correct(q)
            rows.append(
                {
                    "index": idx,
                    "question": q,
                    "given": given,
                    "given_display": ", ".join(given) if given else "-",
                    "correct_display": ", ".join(sorted(correct)),
                    "is_correct": set(given) == correct,
                    "explanation": self.display_explanation(q),
                    "options": [
                        {
                            "letter": letter,
                            "text": text,
                            "chosen": letter in given,
                            "is_correct": letter in correct,
                        }
                        for letter, text in self.display_options(q)
                    ],
                }
            )
        return rows
