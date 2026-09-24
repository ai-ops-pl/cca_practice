# CCAR-F Mock Exam

A self-contained Django app that delivers a 60-item, 120-minute mock exam for the
**Claude Certified Architect – Foundations** certification, built to the blueprint in the
v1.0 exam guide (July 2026).

## Run it

```bash
cd ccar_mock_exam
python3 -m venv .venv && source .venv/bin/activate     # optional
pip install -r requirements.txt
python manage.py migrate
python manage.py load_questions
python manage.py runserver
```

Open http://127.0.0.1:8000/ and start.

## What it does

| | |
|---|---|
| **Items** | 60, weighted to the blueprint: D1 16 (27%), D2 11 (18%), D3 12 (20%), D4 12 (20%), D5 9 (15%) |
| **Scenarios** | All six from the guide, mixed throughout the form |
| **Format** | 52 multiple-choice + 8 multiple-response items; multiple-response items state how many to select and are graded all-or-nothing, as on the real exam |
| **Difficulty** | Calibrated slightly above the guide's sample questions — distractors are plausible and several items turn on a single distinction |
| **Timer** | 120 minutes, enforced server-side. The deadline is stored on the attempt, so closing the tab or refreshing does not reset it. On expiry the attempt auto-submits with whatever is answered |
| **Autosave** | Every answer and flag is persisted as you click; the form also submits correctly with JavaScript disabled |
| **Scoring** | Scaled 100–1,000 with the 720 cut score. Piecewise linear: 0% raw → 100, 70% raw → 720 exactly, 100% raw → 1,000 |
| **Reporting** | Pass/fail, scaled score on a marked scale, raw count, time used, per-domain percentages (diagnostic only, as the guide specifies), and full answer review with an explanation for every item |
| **Retake** | Start a new attempt any time; question order is shuffled by default and previous attempts stay browsable |

## Passing standard

The real exam's cut score comes from a standard-setting study, so no public raw-to-scaled
mapping exists. This app models it as a piecewise-linear curve anchored at 720 = 70% raw
(42/60), which is the conventional shape for a scaled criterion-referenced exam. To change
the anchor, edit `CUT_RAW` in `config/settings.py` — everything else follows from it.

## Editing the question bank

Questions live in `exam/data/questions.json`. Each entry:

```json
{
  "id": 1,
  "scenario": "Customer Support Resolution Agent",
  "domain": "D1",
  "type": "single",
  "question": "...",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "correct": ["A"],
  "explanation": "..."
}
```

Set `"type": "multi"` and list two or more letters in `correct` for a multiple-response item.
Then reload:

```bash
python manage.py load_questions          # upsert by id
python manage.py load_questions --flush  # wipe and reload
```

You can also edit items through the Django admin (`python manage.py createsuperuser`, then
`/admin/`).

## Tests

```bash
python manage.py test exam
```

15 tests cover blueprint weighting, item well-formedness, the cut-score boundary at exactly
42/60, all-or-nothing multiple-response grading, timer expiry and auto-submission, autosave,
and every page render.

## Layout

```
ccar_mock_exam/
├── manage.py
├── requirements.txt
├── config/            settings (exam config lives here), urls, wsgi
├── exam/
│   ├── models.py      Question, Attempt (timing + scoring live on Attempt)
│   ├── views.py       start · take · autosave · submit · results · review
│   ├── tests.py
│   ├── data/questions.json
│   └── management/commands/load_questions.py
└── templates/exam/    base · start · take · results · review
```

Practice material only — not affiliated with or endorsed by Anthropic.
