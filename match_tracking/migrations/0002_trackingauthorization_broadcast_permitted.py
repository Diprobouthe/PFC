from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("match_tracking", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="trackingauthorization",
            name="broadcast_permitted",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
