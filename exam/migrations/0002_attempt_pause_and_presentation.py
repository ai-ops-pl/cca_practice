from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("exam", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="attempt",
            name="paused_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="attempt",
            name="pause_seconds",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="attempt",
            name="presentation",
            field=models.JSONField(default=dict),
        ),
    ]
