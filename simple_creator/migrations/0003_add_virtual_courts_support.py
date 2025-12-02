# Generated migration for virtual courts support

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('simple_creator', '0002_alter_tournamentscenario_tournament_type'),
    ]

    operations = [
        # Add new fields to TournamentScenario
        migrations.AddField(
            model_name='tournamentscenario',
            name='max_courts',
            field=models.PositiveIntegerField(default=4, help_text='Maximum number of courts this scenario can use'),
        ),
        migrations.AddField(
            model_name='tournamentscenario',
            name='recommended_courts',
            field=models.PositiveIntegerField(default=3, help_text='Default/recommended number of courts for this scenario'),
        ),
        migrations.AddField(
            model_name='tournamentscenario',
            name='stages',
            field=models.JSONField(blank=True, null=True, help_text='Multi-stage tournament configuration (JSON format)'),
        ),
        
        # Create VirtualCourt model
        migrations.CreateModel(
            name='VirtualCourt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Virtual court name (e.g., VC-1, VC-2)', max_length=50)),
                ('order', models.PositiveIntegerField(help_text='Display order of the court')),
                ('is_active', models.BooleanField(default=True, help_text='Whether this virtual court is active')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('tournament', models.ForeignKey(help_text='Tournament this virtual court belongs to', on_delete=django.db.models.deletion.CASCADE, related_name='virtual_courts', to='tournaments.tournament')),
            ],
            options={
                'ordering': ['tournament', 'order'],
                'unique_together': {('tournament', 'order')},
            },
        ),
        
        # Make court_complex optional in SimpleTournament (for backward compatibility)
        migrations.AlterField(
            model_name='simpletournament',
            name='court_complex',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='courts.courtcomplex'),
        ),
        
        # Add number of courts field to SimpleTournament
        migrations.AddField(
            model_name='simpletournament',
            name='num_courts',
            field=models.PositiveIntegerField(default=3, help_text='Number of virtual courts for this tournament'),
        ),
        
        # Add flag to indicate if using virtual courts
        migrations.AddField(
            model_name='simpletournament',
            name='uses_virtual_courts',
            field=models.BooleanField(default=True, help_text='Whether this tournament uses virtual courts instead of real venues'),
        ),
    ]

