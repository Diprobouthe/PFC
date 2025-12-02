# Generated data migration to seed initial achievements

from django.db import migrations


def create_initial_achievements(apps, schema_editor):
    """Create initial streak achievements"""
    Achievement = apps.get_model('shooting', 'Achievement')
    
    # Initial achievement configurations as specified
    achievements = [
        {
            'code': 'STREAK_5',
            'name': '5 in a row',
            'description': 'Hit 5 shots in a row without missing',
            'threshold': 5,
            'icon': '🎯',
            'color': '#FFD700',  # Gold
        },
        {
            'code': 'STREAK_10',
            'name': '10 in a row',
            'description': 'Hit 10 shots in a row without missing',
            'threshold': 10,
            'icon': '🔥',
            'color': '#FF6B35',  # Orange-red
        },
        {
            'code': 'STREAK_20',
            'name': '20 in a row',
            'description': 'Hit 20 shots in a row without missing - Master level!',
            'threshold': 20,
            'icon': '👑',
            'color': '#8A2BE2',  # Purple
        },
        {
            'code': 'STREAK_50',
            'name': '50 in a row',
            'description': 'Hit 50 shots in a row - Legendary achievement!',
            'threshold': 50,
            'icon': '⭐',
            'color': '#DC143C',  # Crimson
        },
        {
            'code': 'STREAK_100',
            'name': '100 in a row',
            'description': 'Hit 100 shots in a row - Ultimate mastery!',
            'threshold': 100,
            'icon': '💎',
            'color': '#4169E1',  # Royal blue
        },
    ]
    
    for achievement_data in achievements:
        Achievement.objects.get_or_create(
            code=achievement_data['code'],
            defaults=achievement_data
        )


def remove_initial_achievements(apps, schema_editor):
    """Remove initial achievements if migration is reversed"""
    Achievement = apps.get_model('shooting', 'Achievement')
    
    initial_codes = ['STREAK_5', 'STREAK_10', 'STREAK_20', 'STREAK_50', 'STREAK_100']
    Achievement.objects.filter(code__in=initial_codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('shooting', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(
            create_initial_achievements,
            remove_initial_achievements,
            elidable=True,
        ),
    ]
