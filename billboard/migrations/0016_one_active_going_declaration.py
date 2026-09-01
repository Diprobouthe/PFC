from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone


def close_duplicate_active_going(apps, schema_editor):
    BillboardEntry = apps.get_model("billboard", "BillboardEntry")
    seen = set()
    duplicate_ids = []
    active_entries = (
        BillboardEntry.objects.filter(
            action_type="GOING_TO_COURTS",
            is_active=True,
            going_status="active",
        )
        .order_by("codename", "court_complex_id", "-created_at", "-pk")
        .values_list("pk", "codename", "court_complex_id")
    )
    for entry_id, codename, court_complex_id in active_entries:
        key = (codename, court_complex_id)
        if key in seen:
            duplicate_ids.append(entry_id)
        else:
            seen.add(key)
    if duplicate_ids:
        now = timezone.now()
        BillboardEntry.objects.filter(pk__in=duplicate_ids).update(
            going_status="canceled",
            canceled_at=now,
            is_active=False,
            updated_at=now,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("billboard", "0015_billboardentry_arrived_at_and_more"),
    ]

    operations = [
        migrations.RunPython(close_duplicate_active_going, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="billboardentry",
            constraint=models.UniqueConstraint(
                fields=("codename", "court_complex"),
                condition=Q(
                    action_type="GOING_TO_COURTS",
                    is_active=True,
                    going_status="active",
                ),
                name="unique_active_going_per_player_court",
            ),
        ),
    ]
