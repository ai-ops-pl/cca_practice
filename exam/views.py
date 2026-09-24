import random

from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .formbuild import BankError, build_validated_presentation, validate_bank
from .models import Attempt, Question


def _cfg():
    return settings.EXAM


def start(request):
    ready = Question.objects.count()
    in_progress = None
    attempt_id = request.session.get("attempt_id")
    if attempt_id:
        in_progress = Attempt.objects.filter(pk=attempt_id, submitted_at=None).first()

    bank_errors = validate_bank(list(Question.objects.all())) if ready else [
        "No questions loaded. Run: python manage.py load_questions"
    ]

    context = {
        "cfg": _cfg(),
        "question_count": ready,
        "bank_errors": bank_errors,
        "bank_ok": not bank_errors,
        "in_progress": in_progress,
        "domains": [
            {"key": k, **v, "count": Question.objects.filter(domain=k).count()}
            for k, v in _cfg()["DOMAINS"].items()
        ],
        "recent": Attempt.objects.exclude(submitted_at=None),
    }
    return render(request, "exam/start.html", context)


@require_POST
def begin(request):
    questions = list(Question.objects.all())
    numbers = [q.number for q in questions]
    if not numbers:
        messages.error(request, "No questions loaded. Run: python manage.py load_questions")
        return redirect("start")

    try:
        presentation = build_validated_presentation(questions)
    except BankError as exc:
        messages.error(request, f"Exam cannot start until the bank is valid: {exc}")
        return redirect("start")

    if request.POST.get("shuffle") == "on":
        random.shuffle(numbers)
    else:
        numbers.sort()

    attempt = Attempt.objects.create(
        candidate=request.POST.get("candidate", "").strip()[:120],
        duration_minutes=_cfg()["DURATION_MINUTES"],
        order=numbers,
        answers={},
        flagged=[],
        presentation=presentation,
    )
    request.session["attempt_id"] = str(attempt.id)
    return redirect("take", attempt_id=attempt.id)


def take(request, attempt_id):
    attempt = get_object_or_404(Attempt, pk=attempt_id)
    if attempt.submitted_at:
        return redirect("results", attempt_id=attempt.id)
    if attempt.expired:
        return _finalise(attempt, auto=True) or redirect("results", attempt_id=attempt.id)

    questions = attempt.questions()
    items = []
    for idx, q in enumerate(questions, start=1):
        selected = attempt.answers.get(str(q.number), [])
        items.append(
            {
                "index": idx,
                "q": q,
                "options": attempt.display_options(q),
                "selected": selected,
                "flagged": q.number in attempt.flagged,
            }
        )
    context = {
        "cfg": _cfg(),
        "attempt": attempt,
        "items": items,
        "seconds_remaining": attempt.seconds_remaining,
        "paused": attempt.is_paused,
    }
    return render(request, "exam/take.html", context)


def _read_letters(request):
    letters = [l for l in request.POST.getlist("letters") if l in {"A", "B", "C", "D"}]
    return sorted(set(letters))


@require_POST
def autosave(request, attempt_id):
    """Persist a single answer or flag toggle without a page reload."""
    attempt = get_object_or_404(Attempt, pk=attempt_id)
    if attempt.submitted_at:
        return JsonResponse({"ok": False, "reason": "submitted"}, status=409)
    if attempt.expired:
        _finalise(attempt, auto=True)
        return JsonResponse({"ok": False, "reason": "expired"}, status=409)

    number = str(request.POST.get("number", ""))
    if request.POST.get("action") == "flag":
        num = int(number)
        flags = set(attempt.flagged)
        flags.symmetric_difference_update({num})
        attempt.flagged = sorted(flags)
        attempt.save(update_fields=["flagged"])
        return JsonResponse({"ok": True, "flagged": num in flags, "paused": attempt.is_paused})

    q = Question.objects.filter(number=int(number)).first() if number.isdigit() else None
    letters = _read_letters(request)
    if q and q.qtype == Question.MULTI and len(letters) > q.select_count:
        letters = letters[: q.select_count]

    answers = dict(attempt.answers)
    if letters:
        answers[number] = letters
    else:
        answers.pop(number, None)
    attempt.answers = answers
    attempt.save(update_fields=["answers"])
    return JsonResponse(
        {
            "ok": True,
            "answered": attempt.answered_count,
            "remaining": attempt.seconds_remaining,
            "saved": letters,
            "paused": attempt.is_paused,
        }
    )


@require_POST
def pause_toggle(request, attempt_id):
    attempt = get_object_or_404(Attempt, pk=attempt_id)
    if attempt.submitted_at:
        return JsonResponse({"ok": False, "reason": "submitted"}, status=409)

    want = request.POST.get("state")
    if want == "pause" or (want is None and not attempt.is_paused):
        attempt.pause()
    elif want == "resume" or attempt.is_paused:
        attempt.resume()

    return JsonResponse(
        {
            "ok": True,
            "paused": attempt.is_paused,
            "remaining": attempt.seconds_remaining,
        }
    )


def _finalise(attempt, auto=False):
    if attempt.is_paused:
        attempt.resume()
    attempt.score()
    attempt.submitted_at = timezone.now()
    attempt.auto_submitted = auto
    attempt.save()
    return None


@require_POST
def submit(request, attempt_id):
    attempt = get_object_or_404(Attempt, pk=attempt_id)
    if attempt.submitted_at:
        return redirect("results", attempt_id=attempt.id)

    # A full-form POST is the fallback path when JS autosave is unavailable.
    if request.POST.get("full_form") == "1":
        answers = {}
        for q in attempt.questions():
            letters = request.POST.getlist(f"q{q.number}")
            letters = sorted({l for l in letters if l in {"A", "B", "C", "D"}})
            if q.qtype == Question.MULTI:
                letters = letters[: q.select_count]
            if letters:
                answers[str(q.number)] = letters
        attempt.answers = answers

    auto = (not attempt.is_paused and attempt.expired) or request.POST.get("auto") == "1"
    _finalise(attempt, auto=auto)
    return redirect("results", attempt_id=attempt.id)


def results(request, attempt_id):
    attempt = get_object_or_404(Attempt, pk=attempt_id)
    if not attempt.submitted_at:
        return redirect("take", attempt_id=attempt.id)

    total = len(attempt.order) or 1
    rows = attempt.domain_breakdown()
    max_pct = max([r["percent"] for r in rows] + [1])
    for r in rows:
        r["bar"] = round(100 * r["percent"] / max(max_pct, 1))
    cfg = _cfg()
    span = cfg["SCALED_MAX"] - cfg["SCALED_MIN"]
    context = {
        "cfg": cfg,
        "attempt": attempt,
        "total": total,
        "percent": round(100 * (attempt.raw_correct or 0) / total),
        "rows": rows,
        "score_pos": round(100 * ((attempt.scaled_score or 0) - cfg["SCALED_MIN"]) / span, 2),
        "cut_pos": round(100 * (cfg["CUT_SCORE"] - cfg["SCALED_MIN"]) / span, 2),
        "unanswered": total - attempt.answered_count,
    }
    return render(request, "exam/results.html", context)


def review(request, attempt_id):
    attempt = get_object_or_404(Attempt, pk=attempt_id)
    if not attempt.submitted_at:
        return redirect("take", attempt_id=attempt.id)

    rows = attempt.review_rows()
    only = request.GET.get("only")
    if only == "wrong":
        rows = [r for r in rows if not r["is_correct"]]
    elif only == "right":
        rows = [r for r in rows if r["is_correct"]]
    elif only in _cfg()["DOMAINS"]:
        rows = [r for r in rows if r["question"].domain == only]

    context = {
        "cfg": _cfg(),
        "attempt": attempt,
        "rows": rows,
        "only": only or "all",
        "wrong_count": sum(1 for r in attempt.review_rows() if not r["is_correct"]),
    }
    return render(request, "exam/review.html", context)


def _forget_attempt(request, attempt):
    if str(request.session.get("attempt_id", "")) == str(attempt.id):
        request.session.pop("attempt_id", None)


@require_POST
def delete_attempt(request, attempt_id):
    attempt = get_object_or_404(Attempt, pk=attempt_id)
    _forget_attempt(request, attempt)
    attempt.delete()
    messages.success(request, "That attempt was deleted.")
    return redirect("start")


@require_POST
def delete_all_results(request):
    submitted = Attempt.objects.exclude(submitted_at=None)
    count = submitted.count()
    current = request.session.get("attempt_id")
    if current and submitted.filter(pk=current).exists():
        request.session.pop("attempt_id", None)
    submitted.delete()
    messages.success(
        request,
        "All saved results were deleted." if count else "There were no saved results to delete.",
    )
    return redirect("start")
