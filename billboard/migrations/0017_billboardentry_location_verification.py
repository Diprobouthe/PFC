from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billboard", "0016_one_active_going_declaration"),
    ]

    operations = [
        migrations.AddField(
            model_name="billboardentry",
            name="location_verification",
            field=models.CharField(
                blank=True,
                choices=[
                    ("normal_radius", "Normal radius pass"),
                    ("accuracy_assisted", "Accuracy-assisted pass"),
                    ("user_confirmed_ambiguous", "User-confirmed ambiguous venue"),
                ],
                db_index=True,
                default="",
                help_text="How the manual Court Complex proximity check was verified.",
                max_length=32,
            ),
        ),
    ]
