from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("courts", "0010_courtcomplex_timezone_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="courtcomplex",
            name="latitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                help_text="Latitude of this physical court complex (decimal degrees, e.g. 37.983810)",
                max_digits=9,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="courtcomplex",
            name="longitude",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                help_text="Longitude of this physical court complex (decimal degrees, e.g. 23.727539)",
                max_digits=9,
                null=True,
            ),
        ),
    ]
