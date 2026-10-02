import json
from pathlib import Path

from django.core.management.base import BaseCommand

from exam.models import Question

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class Command(BaseCommand):
    help = "Load (or reload) mock exam question banks. Each JSON file in exam/data is one test."

    def add_arguments(self, parser):
        parser.add_argument("--path", help="Load a single JSON file instead of every file in exam/data.")
        parser.add_argument(
            "--flush", action="store_true", help="Delete existing questions in the loaded banks first."
        )

    def handle(self, *args, **opts):
        paths = [Path(opts["path"])] if opts["path"] else sorted(DATA_DIR.glob("*.json"))
        for path in paths:
            if not path.exists():
                self.stderr.write(f"Question file not found: {path}")
                continue
            self._load(path, opts["flush"])

    def _load(self, path, flush):
        bank = path.stem
        data = json.loads(path.read_text())
        if flush:
            Question.objects.filter(bank=bank).delete()

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
                bank=bank, number=item["id"], defaults=defaults
            )
            created += was_created
            updated += not was_created

        self.stdout.write(
            self.style.SUCCESS(
                f"[{bank}] Loaded {len(data)} questions ({created} created, {updated} updated)."
            )
        )
