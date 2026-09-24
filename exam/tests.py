"""End-to-end checks for the mock exam engine."""

from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from .formbuild import BankError, build_validated_presentation, presentation_is_well_mixed, validate_bank
from .models import LETTERS, Attempt, Question


class ExamFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_questions", verbosity=0)

    def _correct(self, attempt, q):
        return sorted(attempt.display_correct(q))

    # -- bank integrity ----------------------------------------------------
    def test_bank_matches_blueprint(self):
        self.assertEqual(Question.objects.count(), settings.EXAM["ITEM_COUNT"])
        counts = {d: Question.objects.filter(domain=d).count() for d in settings.EXAM["DOMAINS"]}
        self.assertEqual(counts, {"D1": 16, "D2": 11, "D3": 12, "D4": 12, "D5": 9})
        for key, meta in settings.EXAM["DOMAINS"].items():
            share = 100 * counts[key] / settings.EXAM["ITEM_COUNT"]
            self.assertLess(abs(share - meta["weight"]), 1.5, f"{key} share {share:.1f}%")

    def test_every_question_is_well_formed(self):
        for q in Question.objects.all():
            self.assertTrue(q.correct_set <= {"A", "B", "C", "D"}, q.number)
            self.assertEqual(q.qtype == "multi", len(q.correct_set) > 1, q.number)
            for _, text in q.options():
                self.assertTrue(text.strip(), q.number)
            self.assertTrue(q.explanation.strip(), q.number)

    def test_bank_validation_passes(self):
        self.assertEqual(validate_bank(list(Question.objects.all())), [])

    def test_source_bank_puts_correct_answers_on_a(self):
        """The authored file keys every item to A (or A,B). Shuffling must hide that."""
        singles = Question.objects.filter(qtype="single")
        self.assertTrue(all(q.correct_set == {"A"} for q in singles))

    def test_multi_response_items_exist(self):
        self.assertGreaterEqual(Question.objects.filter(qtype="multi").count(), 5)

    # -- full candidate journey -------------------------------------------
    def _start(self):
        resp = self.client.post("/begin/", {"candidate": "AK", "shuffle": "on"}, follow=True)
        self.assertEqual(resp.status_code, 200)
        return Attempt.objects.latest("started_at")

    def test_perfect_score(self):
        attempt = self._start()
        payload = {"full_form": "1"}
        for q in attempt.questions():
            payload[f"q{q.number}"] = self._correct(attempt, q)
        self.client.post(f"/attempt/{attempt.id}/submit/", payload)
        attempt.refresh_from_db()
        self.assertEqual(attempt.raw_correct, 60)
        self.assertEqual(attempt.scaled_score, settings.EXAM["SCALED_MAX"])
        self.assertTrue(attempt.passed)

    def test_cut_score_boundary(self):
        """42/60 = 70% raw must map exactly to the 720 cut score and pass."""
        attempt = self._start()
        payload = {"full_form": "1"}
        for i, q in enumerate(attempt.questions()):
            wrong = sorted({"A", "B", "C", "D"} - attempt.display_correct(q))[:1]
            payload[f"q{q.number}"] = self._correct(attempt, q) if i < 42 else wrong
        self.client.post(f"/attempt/{attempt.id}/submit/", payload)
        attempt.refresh_from_db()
        self.assertEqual(attempt.raw_correct, 42)
        self.assertEqual(attempt.scaled_score, 720)
        self.assertTrue(attempt.passed)

    def test_one_below_cut_fails(self):
        attempt = self._start()
        payload = {"full_form": "1"}
        for i, q in enumerate(attempt.questions()):
            if i < 41:
                payload[f"q{q.number}"] = self._correct(attempt, q)
        self.client.post(f"/attempt/{attempt.id}/submit/", payload)
        attempt.refresh_from_db()
        self.assertEqual(attempt.raw_correct, 41)
        self.assertLess(attempt.scaled_score, 720)
        self.assertFalse(attempt.passed)

    def test_multi_response_is_all_or_nothing(self):
        attempt = self._start()
        multi = next(q for q in attempt.questions() if q.qtype == "multi")
        correct = attempt.display_correct(multi)
        partial = sorted(correct)[:1]
        attempt.answers = {str(multi.number): partial}
        result = attempt.score()
        self.assertEqual(result["correct"], 0, "partial credit must not be awarded")

        attempt.answers = {str(multi.number): sorted(correct)}
        self.assertEqual(attempt.score()["correct"], 1)

        # Selecting every option (a superset) is also wrong.
        attempt.answers = {str(multi.number): sorted(correct | ({"A", "B", "C", "D"} - correct))}
        self.assertEqual(attempt.score()["correct"], 0)

    def test_autosave_keeps_both_multi_select_letters(self):
        attempt = self._start()
        multi = next(q for q in attempt.questions() if q.qtype == "multi")
        letters = self._correct(attempt, multi)
        self.assertEqual(len(letters), 2)
        self.client.post(
            f"/attempt/{attempt.id}/autosave/",
            {"number": multi.number, "letters": letters},
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.answers[str(multi.number)], letters)
        take = self.client.get(f"/attempt/{attempt.id}/")
        self.assertContains(take, 'type="checkbox"')
        for letter in letters:
            self.assertContains(take, f'value="{letter}"')

    def test_domain_breakdown_totals(self):
        attempt = self._start()
        attempt.answers = {
            str(q.number): self._correct(attempt, q)
            for q in attempt.questions()
            if q.domain in {"D1", "D3"}
        }
        attempt.save()
        rows = {r["key"]: r for r in attempt.domain_breakdown()}
        self.assertEqual(rows["D1"]["percent"], 100)
        self.assertEqual(rows["D3"]["percent"], 100)
        self.assertEqual(rows["D5"]["percent"], 0)
        self.assertEqual(sum(r["total"] for r in rows.values()), 60)

    # -- option shuffle ----------------------------------------------------
    def test_begin_shuffles_correct_letters_off_a(self):
        attempt = self._start()
        self.assertTrue(attempt.presentation)
        singles = [q for q in attempt.questions() if q.qtype == "single"]
        display = [next(iter(attempt.display_correct(q))) for q in singles]
        self.assertGreater(len(set(display)), 1)
        self.assertLess(display.count("A") / len(display), 0.51)
        self.assertTrue(presentation_is_well_mixed(list(attempt.questions()), attempt.presentation))

    def test_shuffled_review_marks_display_letters(self):
        attempt = self._start()
        q = next(x for x in attempt.questions() if x.qtype == "single")
        slots = attempt.slots_for(q)
        self.assertEqual(set(slots), set(LETTERS))
        correct_display = next(iter(attempt.display_correct(q)))
        orig = slots[LETTERS.index(correct_display)]
        self.assertIn(orig, q.correct_set)
        attempt.answers = {str(q.number): [correct_display]}
        row = next(r for r in attempt.review_rows() if r["question"].number == q.number)
        self.assertTrue(row["is_correct"])
        marked = [o["letter"] for o in row["options"] if o["is_correct"]]
        self.assertEqual(marked, [correct_display])

    def test_cannot_start_with_empty_bank(self):
        Question.objects.all().delete()
        resp = self.client.post("/begin/", {"candidate": "AK"}, follow=True)
        self.assertContains(resp, "No questions loaded")
        self.assertEqual(Attempt.objects.count(), 0)

    # -- timer / pause -----------------------------------------------------
    def test_duration_is_two_hours(self):
        attempt = self._start()
        self.assertEqual(attempt.duration_minutes, 120)
        self.assertAlmostEqual(attempt.seconds_remaining, 7200, delta=5)

    def test_pause_freezes_remaining_time(self):
        attempt = self._start()
        self.client.post(f"/attempt/{attempt.id}/pause/", {"state": "pause"})
        attempt.refresh_from_db()
        self.assertTrue(attempt.is_paused)
        before = attempt.seconds_remaining
        drift = timedelta(minutes=15)
        attempt.started_at -= drift
        attempt.paused_at -= drift
        attempt.save(update_fields=["started_at", "paused_at"])
        frozen = attempt.seconds_remaining
        self.assertAlmostEqual(frozen, before, delta=5)
        self.assertFalse(attempt.expired)

        self.client.post(f"/attempt/{attempt.id}/pause/", {"state": "resume"})
        attempt.refresh_from_db()
        self.assertFalse(attempt.is_paused)
        self.assertGreaterEqual(attempt.pause_seconds, 15 * 60 - 2)
        self.assertAlmostEqual(attempt.seconds_remaining, frozen, delta=5)

    def test_expired_attempt_auto_submits_on_access(self):
        attempt = self._start()
        first = attempt.questions()[0]
        attempt.answers = {str(first.number): self._correct(attempt, first)}
        attempt.started_at = timezone.now() - timedelta(minutes=121)
        attempt.save()
        self.assertTrue(attempt.expired)

        resp = self.client.get(f"/attempt/{attempt.id}/", follow=True)
        self.assertEqual(resp.status_code, 200)
        attempt.refresh_from_db()
        self.assertIsNotNone(attempt.submitted_at)
        self.assertTrue(attempt.auto_submitted)
        self.assertEqual(attempt.raw_correct, 1)

    def test_paused_attempt_does_not_expire(self):
        attempt = self._start()
        attempt.pause()
        attempt.started_at = timezone.now() - timedelta(minutes=200)
        attempt.paused_at = timezone.now() - timedelta(minutes=80)
        attempt.save()
        self.assertFalse(attempt.expired)
        resp = self.client.get(f"/attempt/{attempt.id}/")
        self.assertEqual(resp.status_code, 200)
        attempt.refresh_from_db()
        self.assertIsNone(attempt.submitted_at)

    # -- autosave and navigation ------------------------------------------
    def test_autosave_persists_answer_and_flag(self):
        attempt = self._start()
        q = attempt.questions()[0]
        self.client.post(
            f"/attempt/{attempt.id}/autosave/", {"number": q.number, "letters": ["A"]}
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.answers[str(q.number)], ["A"])

        self.client.post(f"/attempt/{attempt.id}/autosave/", {"number": q.number, "letters": []})
        attempt.refresh_from_db()
        self.assertNotIn(str(q.number), attempt.answers)

        self.client.post(
            f"/attempt/{attempt.id}/autosave/", {"action": "flag", "number": q.number}
        )
        attempt.refresh_from_db()
        self.assertIn(q.number, attempt.flagged)

    def test_autosave_rejected_after_submission(self):
        attempt = self._start()
        self.client.post(f"/attempt/{attempt.id}/submit/", {"full_form": "1"})
        q = attempt.questions()[0]
        resp = self.client.post(
            f"/attempt/{attempt.id}/autosave/", {"number": q.number, "letters": ["A"]}
        )
        self.assertEqual(resp.status_code, 409)

    def test_pages_render(self):
        attempt = self._start()
        home = self.client.get("/")
        self.assertContains(home, "Blueprint coverage")
        self.assertContains(home, "Bank validated")
        self.assertContains(home, "Toggle dark mode")
        take = self.client.get(f"/attempt/{attempt.id}/")
        self.assertContains(take, "Question 60")
        self.assertContains(take, "Navigator")
        self.assertContains(take, "Pause")

        self.client.post(f"/attempt/{attempt.id}/submit/", {"full_form": "1"})
        self.assertContains(self.client.get(f"/attempt/{attempt.id}/results/"), "Score report")
        review = self.client.get(f"/attempt/{attempt.id}/review/?only=wrong")
        self.assertContains(review, "Why")

    def test_finished_attempt_redirects_away_from_exam(self):
        attempt = self._start()
        self.client.post(f"/attempt/{attempt.id}/submit/", {"full_form": "1"})
        resp = self.client.get(f"/attempt/{attempt.id}/")
        self.assertRedirects(resp, f"/attempt/{attempt.id}/results/")

    def test_retake_creates_independent_attempt(self):
        first = self._start()
        self.client.post(f"/attempt/{first.id}/submit/", {"full_form": "1"})
        second = self._start()
        self.assertNotEqual(first.id, second.id)
        self.assertIsNone(second.submitted_at)
        self.assertEqual(len(second.order), 60)
        self.assertNotEqual(first.presentation, second.presentation)

    def test_build_validated_presentation_requires_questions(self):
        with self.assertRaises(BankError):
            build_validated_presentation([])

    def test_delete_one_result(self):
        attempt = self._start()
        self.client.post(f"/attempt/{attempt.id}/submit/", {"full_form": "1"})
        self.assertTrue(Attempt.objects.filter(pk=attempt.id).exists())
        resp = self.client.post(f"/attempt/{attempt.id}/delete/", follow=True)
        self.assertContains(resp, "That attempt was deleted.")
        self.assertFalse(Attempt.objects.filter(pk=attempt.id).exists())
        self.assertContains(resp, "Blueprint coverage")

    def test_delete_all_results_keeps_in_progress(self):
        first = self._start()
        self.client.post(f"/attempt/{first.id}/submit/", {"full_form": "1"})
        second = self._start()
        self.client.post("/results/delete-all/", follow=True)
        self.assertFalse(Attempt.objects.filter(pk=first.id).exists())
        self.assertTrue(Attempt.objects.filter(pk=second.id, submitted_at=None).exists())

    # -- CS-1: Single attempt deletion ------------------------------------
    def test_delete_single_attempt_others_remain(self):
        """AC1: Delete a single finished attempt; other attempts remain."""
        first = self._start()
        self.client.post(f"/attempt/{first.id}/submit/", {"full_form": "1"})
        second = self._start()
        self.client.post(f"/attempt/{second.id}/submit/", {"full_form": "1"})
        third = self._start()
        self.client.post(f"/attempt/{third.id}/submit/", {"full_form": "1"})

        self.assertEqual(Attempt.objects.filter(submitted_at__isnull=False).count(), 3)
        self.client.post(f"/attempt/{second.id}/delete/")
        self.assertEqual(Attempt.objects.filter(submitted_at__isnull=False).count(), 2)
        self.assertTrue(Attempt.objects.filter(pk=first.id).exists())
        self.assertFalse(Attempt.objects.filter(pk=second.id).exists())
        self.assertTrue(Attempt.objects.filter(pk=third.id).exists())

    def test_delete_from_results_redirects_to_start(self):
        """AC2: Delete from score report redirects to start page."""
        attempt = self._start()
        self.client.post(f"/attempt/{attempt.id}/submit/", {"full_form": "1"})
        resp = self.client.post(f"/attempt/{attempt.id}/delete/")
        self.assertRedirects(resp, "/")
        self.assertFalse(Attempt.objects.filter(pk=attempt.id).exists())

    def test_discard_in_progress_attempt(self):
        """AC3: Discard an in-progress attempt from start-page banner."""
        attempt = self._start()
        self.assertIsNone(attempt.submitted_at)
        self.assertEqual(Attempt.objects.filter(submitted_at=None).count(), 1)
        resp = self.client.post(f"/attempt/{attempt.id}/delete/", follow=True)
        self.assertContains(resp, "That attempt was deleted.")
        self.assertFalse(Attempt.objects.filter(pk=attempt.id).exists())
        self.assertEqual(Attempt.objects.filter(submitted_at=None).count(), 0)

    def test_discard_paused_attempt(self):
        """AC3: Discard a paused attempt from start-page banner."""
        attempt = self._start()
        self.client.post(f"/attempt/{attempt.id}/pause/", {"state": "pause"})
        attempt.refresh_from_db()
        self.assertTrue(attempt.is_paused)
        self.client.post(f"/attempt/{attempt.id}/delete/")
        self.assertFalse(Attempt.objects.filter(pk=attempt.id).exists())

    def test_deleted_attempt_urls_return_404(self):
        """AC5: After delete, history/results/review URLs return 404."""
        attempt = self._start()
        self.client.post(f"/attempt/{attempt.id}/submit/", {"full_form": "1"})
        self.client.post(f"/attempt/{attempt.id}/delete/")
        
        resp_take = self.client.get(f"/attempt/{attempt.id}/")
        self.assertEqual(resp_take.status_code, 404)
        resp_results = self.client.get(f"/attempt/{attempt.id}/results/")
        self.assertEqual(resp_results.status_code, 404)
        resp_review = self.client.get(f"/attempt/{attempt.id}/review/")
        self.assertEqual(resp_review.status_code, 404)

    def test_delete_clears_session_pointer(self):
        """AC6: If deleted attempt is in session, clear the session pointer."""
        attempt = self._start()
        self.assertEqual(self.client.session.get("attempt_id"), str(attempt.id))
        self.client.post(f"/attempt/{attempt.id}/delete/")
        self.assertIsNone(self.client.session.get("attempt_id"))

    def test_delete_clears_session_for_finished_attempt(self):
        """AC6: Clear session pointer even for finished attempts."""
        attempt = self._start()
        self.client.post(f"/attempt/{attempt.id}/submit/", {"full_form": "1"})
        self.assertEqual(self.client.session.get("attempt_id"), str(attempt.id))
        self.client.post(f"/attempt/{attempt.id}/delete/")
        self.assertIsNone(self.client.session.get("attempt_id"))

    def test_delete_other_attempt_preserves_session(self):
        """AC6: Deleting another attempt preserves current session pointer."""
        first = self._start()
        self.client.post(f"/attempt/{first.id}/submit/", {"full_form": "1"})
        second = self._start()
        self.assertEqual(self.client.session.get("attempt_id"), str(second.id))
        self.client.post(f"/attempt/{first.id}/delete/")
        self.assertEqual(self.client.session.get("attempt_id"), str(second.id))
        self.assertTrue(Attempt.objects.filter(pk=second.id).exists())

    def test_delete_is_post_only(self):
        """AC8: Delete is POST only; GET must not delete."""
        attempt = self._start()
        self.client.post(f"/attempt/{attempt.id}/submit/", {"full_form": "1"})
        resp = self.client.get(f"/attempt/{attempt.id}/delete/")
        self.assertEqual(resp.status_code, 405)  # Method Not Allowed
        self.assertTrue(Attempt.objects.filter(pk=attempt.id).exists())

    # -- CS-3: Multi-select delete ----------------------------------------
    def test_multi_select_delete_removes_selected_only(self):
        """AC1,3: Delete only selected finished attempts; unselected remain."""
        first = self._start()
        self.client.post(f"/attempt/{first.id}/submit/", {"full_form": "1"})
        second = self._start()
        self.client.post(f"/attempt/{second.id}/submit/", {"full_form": "1"})
        third = self._start()
        self.client.post(f"/attempt/{third.id}/submit/", {"full_form": "1"})
        
        self.assertEqual(Attempt.objects.filter(submitted_at__isnull=False).count(), 3)
        
        # Delete first and third, keep second
        resp = self.client.post(
            "/results/delete-selected/",
            {"attempt_ids": [str(first.id), str(third.id)]},
            follow=True
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Attempt.objects.filter(pk=first.id).exists())
        self.assertTrue(Attempt.objects.filter(pk=second.id).exists())
        self.assertFalse(Attempt.objects.filter(pk=third.id).exists())
        self.assertEqual(Attempt.objects.filter(submitted_at__isnull=False).count(), 1)

    def test_multi_select_delete_one_attempt(self):
        """AC1: Multi-select can delete just one attempt."""
        attempt = self._start()
        self.client.post(f"/attempt/{attempt.id}/submit/", {"full_form": "1"})
        
        resp = self.client.post(
            "/results/delete-selected/",
            {"attempt_ids": [str(attempt.id)]},
            follow=True
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Attempt.objects.filter(pk=attempt.id).exists())

    def test_multi_select_ignores_in_progress_attempts(self):
        """AC4: In-progress/paused attempts not deletable via multi-select."""
        finished = self._start()
        self.client.post(f"/attempt/{finished.id}/submit/", {"full_form": "1"})
        in_progress = self._start()
        paused = self._start()
        self.client.post(f"/attempt/{paused.id}/pause/", {"state": "pause"})
        
        # Try to delete all three; only finished should be deleted
        resp = self.client.post(
            "/results/delete-selected/",
            {"attempt_ids": [str(finished.id), str(in_progress.id), str(paused.id)]},
            follow=True
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Attempt.objects.filter(pk=finished.id).exists())
        self.assertTrue(Attempt.objects.filter(pk=in_progress.id).exists())
        self.assertTrue(Attempt.objects.filter(pk=paused.id).exists())

    def test_multi_select_delete_returns_404(self):
        """AC5: After multi-select delete, URLs return 404."""
        first = self._start()
        self.client.post(f"/attempt/{first.id}/submit/", {"full_form": "1"})
        second = self._start()
        self.client.post(f"/attempt/{second.id}/submit/", {"full_form": "1"})
        
        self.client.post(
            "/results/delete-selected/",
            {"attempt_ids": [str(first.id), str(second.id)]}
        )
        
        self.assertEqual(self.client.get(f"/attempt/{first.id}/results/").status_code, 404)
        self.assertEqual(self.client.get(f"/attempt/{second.id}/review/").status_code, 404)

    def test_multi_select_delete_clears_session(self):
        """AC6: Clear session pointer if current attempt is deleted."""
        first = self._start()
        self.client.post(f"/attempt/{first.id}/submit/", {"full_form": "1"})
        second = self._start()
        self.client.post(f"/attempt/{second.id}/submit/", {"full_form": "1"})
        
        # Session points to second
        self.assertEqual(self.client.session.get("attempt_id"), str(second.id))
        
        # Delete both including current
        self.client.post(
            "/results/delete-selected/",
            {"attempt_ids": [str(first.id), str(second.id)]}
        )
        self.assertIsNone(self.client.session.get("attempt_id"))

    def test_multi_select_delete_preserves_session_if_not_deleted(self):
        """AC6: Preserve session if current attempt not in selection."""
        first = self._start()
        self.client.post(f"/attempt/{first.id}/submit/", {"full_form": "1"})
        second = self._start()
        self.client.post(f"/attempt/{second.id}/submit/", {"full_form": "1"})
        
        self.assertEqual(self.client.session.get("attempt_id"), str(second.id))
        
        # Delete only first
        self.client.post("/results/delete-selected/", {"attempt_ids": [str(first.id)]})
        self.assertEqual(self.client.session.get("attempt_id"), str(second.id))

    def test_single_delete_still_works(self):
        """AC7: Existing single delete remains available."""
        first = self._start()
        self.client.post(f"/attempt/{first.id}/submit/", {"full_form": "1"})
        second = self._start()
        self.client.post(f"/attempt/{second.id}/submit/", {"full_form": "1"})
        
        # Use old single-delete endpoint
        self.client.post(f"/attempt/{first.id}/delete/")
        self.assertFalse(Attempt.objects.filter(pk=first.id).exists())
        self.assertTrue(Attempt.objects.filter(pk=second.id).exists())

    def test_delete_all_still_works_with_multi_select(self):
        """AC7: Existing delete-all remains available."""
        first = self._start()
        self.client.post(f"/attempt/{first.id}/submit/", {"full_form": "1"})
        second = self._start()
        self.client.post(f"/attempt/{second.id}/submit/", {"full_form": "1"})
        in_progress = self._start()
        
        self.client.post("/results/delete-all/", follow=True)
        self.assertFalse(Attempt.objects.filter(pk=first.id).exists())
        self.assertFalse(Attempt.objects.filter(pk=second.id).exists())
        self.assertTrue(Attempt.objects.filter(pk=in_progress.id).exists())

    def test_multi_select_delete_is_post_only(self):
        """AC8: Multi-delete is POST only; GET must not delete."""
        attempt = self._start()
        self.client.post(f"/attempt/{attempt.id}/submit/", {"full_form": "1"})
        
        resp = self.client.get("/results/delete-selected/")
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(Attempt.objects.filter(pk=attempt.id).exists())

    def test_multi_select_delete_with_no_selection(self):
        """Multi-select with empty selection redirects without error."""
        attempt = self._start()
        self.client.post(f"/attempt/{attempt.id}/submit/", {"full_form": "1"})
        
        resp = self.client.post("/results/delete-selected/", {"attempt_ids": []}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Attempt.objects.filter(pk=attempt.id).exists())

    def test_multi_select_delete_with_invalid_ids(self):
        """Multi-select ignores non-existent or invalid attempt IDs."""
        attempt = self._start()
        self.client.post(f"/attempt/{attempt.id}/submit/", {"full_form": "1"})
        
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = self.client.post(
            "/results/delete-selected/",
            {"attempt_ids": [str(attempt.id), fake_id]},
            follow=True
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Attempt.objects.filter(pk=attempt.id).exists())
