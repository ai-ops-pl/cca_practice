import json
from pathlib import Path

from django.core.management.base import BaseCommand

from exam.models import Question

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "questions.json"


class Command(BaseCommand):
    help = "Load (or reload) the mock exam question bank from a JSON file."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=str(DEFAULT_PATH))
        parser.add_argument(
            "--flush", action="store_true", help="Delete existing questions before loading."
        )

    def handle(self, *args, **opts):
        path = Path(opts["path"])
        if not path.exists():
            self.stderr.write(f"Question file not found: {path}")
            return

        data = json.loads(path.read_text())
        if opts["flush"]:
            Question.objects.all().delete()

        created = updated = 0
        for item in data:
            letters = item["options"]
            defaults = {
                "scenario": item["scenario"],
                "domain": item["domain"],
                "qtype": item["type"],
                "text": item["question"],
                "option_a": letters["A"],
                "option_b": letters["B"],
                "option_c": letters["C"],
                "option_d": letters["D"],
                "correct": ",".join(item["correct"]),
                "explanation": item["explanation"],
            }
            _, was_created = Question.objects.update_or_create(
                number=item["id"], defaults=defaults
            )
            created += was_created
            updated += not was_created

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(data)} questions ({created} created, {updated} updated)."
            )
        )
