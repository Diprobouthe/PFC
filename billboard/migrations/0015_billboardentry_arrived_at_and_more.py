from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billboard", "0014_billboardentry_going_arrival_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="billboardentry",
            name="arrived_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="When an active Going declaration was completed by a successful manual check-in.",
            ),
        ),
        migrations.AlterField(
            model_name="billboardentry",
            name="going_status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("arrived", "Arrived"),
                    ("canceled", "Canceled"),
                ],
                db_index=True,
                default="active",
                help_text="Active, arrived, or canceled state for Going to courts declarations.",
                max_length=12,
            ),
        ),
    ]
