# Data migration to seed initial achievements

from django.db import migrations


def create_initial_achievements(apps, schema_editor):
    """Create initial achievement records"""
    Achievement = apps.get_model('shooting', 'Achievement')
    
    initial_achievements = [
        {
            'code': 'STREAK_5',
            'name': '5 in a row',
            'description': 'Hit 5 consecutive shots',
            'threshold': 5,
            'icon': '🎯',
            'color': '#28a745',
        },
        {
            'code': 'STREAK_10',
            'name': '10 in a row',
            'description': 'Hit 10 consecutive shots',
            'threshold': 10,
            'icon': '🔥',
            'color': '#fd7e14',
        },
        {
            'code': 'STREAK_20',
            'name': '20 in a row',
            'description': 'Hit 20 consecutive shots - Amazing!',
            'threshold': 20,
            'icon': '⭐',
            'color': '#ffc107',
        },
        {
            'code': 'STREAK_50',
            'name': '50 in a row',
            'description': 'Hit 50 consecutive shots - Legendary!',
            'threshold': 50,
            'icon': '👑',
            'color': '#6f42c1',
        },
    ]
    
    for achievement_data in initial_achievements:
        Achievement.objects.get_or_create(
            code=achievement_data['code'],
            defaults=achievement_data
        )


def reverse_achievements(apps, schema_editor):
    """Remove initial achievements"""
    Achievement = apps.get_model('shooting', 'Achievement')
    codes = ['STREAK_5', 'STREAK_10', 'STREAK_20', 'STREAK_50']
    Achievement.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('shooting', '0003_initial_shooting_models'),
    ]

    operations = [
        migrations.RunPython(create_initial_achievements, reverse_achievements),
    ]
