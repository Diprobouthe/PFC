"""
Utility functions for simple tournament creation
"""
import random
import string
from django.utils import timezone
from datetime import timedelta
from tournaments.models import Tournament, Stage
from teams.models import Team
from courts.models import Court


def generate_team_pins(teams, pin_length=4):
    """Generate unique PINs for teams"""
    used_pins = set()
    
    for team in teams:
        if not team.pin:  # Only generate if team doesn't have a PIN
            while True:
                pin = ''.join(random.choices(string.digits, k=pin_length))
                if pin not in used_pins:
                    team.pin = pin
                    team.save()
                    used_pins.add(pin)
                    break


def auto_assign_courts(tournament, court_complex, max_courts=5):
    """Automatically assign available courts to tournament"""
    available_courts = Court.objects.filter(
        court_complex=court_complex,
        is_available=True
    )[:max_courts]
    
    assigned_count = 0
    for court in available_courts:
        tournament.courts.add(court)
        assigned_count += 1
    
    return assigned_count


def create_tournament_stages(tournament, scenario):
    """Create tournament stages based on scenario configuration"""
    stage = Stage.objects.create(
        tournament=tournament,
        name="Main Stage",
        stage_number=1,
        stage_type=scenario.tournament_type,
        num_qualifiers=1,  # Winner takes all for simple tournaments
        is_complete=False
    )
    
    # Set stage-specific parameters based on scenario
    if scenario.tournament_type == 'swiss':
        stage.num_rounds = scenario.num_rounds
    elif scenario.tournament_type == 'partial_robin':
        stage.matches_per_team = scenario.matches_per_team
    
    stage.save()
    return stage


def get_tournament_summary(simple_tournament):
    """Get a summary of tournament details for display"""
    tournament = simple_tournament.tournament
    
    summary = {
        'name': tournament.name,
        'scenario': simple_tournament.scenario.display_name,
        'format': simple_tournament.format_type.title(),
        'court_complex': simple_tournament.court_complex.name,
        'start_date': simple_tournament.auto_start_date,
        'end_date': simple_tournament.auto_end_date,
        'max_players': simple_tournament.get_max_players(),
        'is_free': simple_tournament.scenario.is_free,
        'voucher_used': simple_tournament.voucher_used.code if simple_tournament.voucher_used else None,
        'tournament_type': simple_tournament.scenario.get_tournament_type_display(),
        'draft_type': simple_tournament.scenario.get_draft_type_display(),
        'assigned_courts': tournament.courts.count(),
        'registered_players': tournament.meleeplayer_set.count(),
        'teams_generated': tournament.melee_teams_generated,
        'is_completed': simple_tournament.is_completed,
        'cleanup_status': {
            'badges_assigned': simple_tournament.badges_assigned,
            'players_restored': simple_tournament.players_restored,
            'mele_teams_deleted': simple_tournament.mele_teams_deleted,
        }
    }
    
    return summary


def validate_tournament_creation(form_data):
    """Validate tournament creation data"""
    errors = []
    
    scenario = form_data.get('scenario')
    format_type = form_data.get('format_type')
    court_complex = form_data.get('court_complex')
    
    if not scenario:
        errors.append("Scenario is required")
    
    if not format_type:
        errors.append("Format type is required")
    
    if not court_complex:
        errors.append("Court complex is required")
    
    # Check if court complex has available courts
    if court_complex:
        available_courts = Court.objects.filter(
            court_complex=court_complex,
            is_available=True
        ).count()
        
        if available_courts == 0:
            errors.append(f"No available courts at {court_complex.name}")
    
    # Validate voucher if scenario requires it
    if scenario and scenario.requires_voucher and not scenario.is_free:
        voucher_object = form_data.get('voucher_object')
        if not voucher_object:
            errors.append("Valid voucher code is required for this scenario")
    
    return errors


def cleanup_tournament_data(simple_tournament):
    """Clean up tournament data after completion"""
    tournament = simple_tournament.tournament
    cleanup_summary = {
        'badges_assigned': 0,
        'players_restored': 0,
        'teams_deleted': 0,
        'errors': []
    }
    
    try:
        # Assign badges (placeholder for future implementation)
        if not simple_tournament.badges_assigned:
            # TODO: Implement badge assignment when system supports it
            simple_tournament.badges_assigned = True
            cleanup_summary['badges_assigned'] = 1
        
        # Restore players to original teams
        if not simple_tournament.players_restored:
            restored_count = tournament.restore_melee_players_to_original_teams()
            simple_tournament.players_restored = True
            cleanup_summary['players_restored'] = restored_count
        
        # Delete empty mêlée teams
        if not simple_tournament.mele_teams_deleted:
            mele_teams = tournament.teams.filter(name__startswith='Mêlée Team')
            deleted_count = 0
            for team in mele_teams:
                if team.players.count() == 0:  # Only delete if empty
                    team.delete()
                    deleted_count += 1
            
            simple_tournament.mele_teams_deleted = True
            cleanup_summary['teams_deleted'] = deleted_count
        
        # Save the updated status
        simple_tournament.save()
        
    except Exception as e:
        cleanup_summary['errors'].append(str(e))
    
    return cleanup_summary

