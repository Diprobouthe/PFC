# Generated for PETA podium awards default enablement.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cert_ratings", "0002_peta_algorithm"),
    ]

    operations = [
        migrations.AlterField(
            model_name="petaevent",
            name="include_podium",
            field=models.BooleanField(default=True),
        ),
    ]
