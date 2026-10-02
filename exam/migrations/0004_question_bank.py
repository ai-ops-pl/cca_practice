from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exam', '0003_attempt_form_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='question',
            name='bank',
            field=models.CharField(db_index=True, default='questions', max_length=64),
        ),
        migrations.AlterField(
            model_name='question',
            name='number',
            field=models.PositiveIntegerField(),
        ),
        migrations.AlterModelOptions(
            name='question',
            options={'ordering': ['bank', 'number']},
        ),
        migrations.AddConstraint(
            model_name='question',
            constraint=models.UniqueConstraint(fields=('bank', 'number'), name='unique_bank_number'),
        ),
        migrations.AddField(
            model_name='attempt',
            name='bank',
            field=models.CharField(default='questions', max_length=64),
        ),
    ]
