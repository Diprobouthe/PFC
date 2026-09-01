from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billboard", "0013_billboardentry_available_for_friendly"),
        ("billboard", "0013_userpresenceprefs_available_for_friendly"),
    ]

    operations = [
        migrations.AddField(
            model_name="billboardentry",
            name="arrival_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text="Exact expected arrival moment, stored in UTC and interpreted in the Court Complex timezone.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="billboardentry",
            name="canceled_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When a Going to courts declaration was canceled by its player.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="billboardentry",
            name="going_status",
            field=models.CharField(
                choices=[("active", "Active"), ("canceled", "Canceled")],
                db_index=True,
                default="active",
                help_text="Active or canceled state for Going to courts declarations.",
                max_length=12,
            ),
        ),
    ]
