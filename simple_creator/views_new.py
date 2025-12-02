"""
Simple tournament creation - SIMPLIFIED VERSION
Only uses real courts from scenario's court complex
"""
from django.db import transaction
from django.utils import timezone
from datetime import datetime, timedelta
from tournaments.models import Tournament, TournamentCourt, Stage
from courts.models import Court
from .models import SimpleTournament, VoucherCode


def create_simple_tournament(form_data):
    """
    Create a simple tournament with real courts only.
    
    Args:
        form_data: Dict with keys:
            - scenario: TournamentScenario object
            - format_type: 'doubles' or 'triples'
            - num_courts: Number of courts to use (int)
            - voucher_code: Optional voucher code (str)
    
    Returns:
        SimpleTournament object
    
    Raises:
        ValueError: If court complex not set or insufficient courts available
    """
    scenario = form_data['scenario']
    format_type = form_data['format_type']
    num_courts = form_data['num_courts']
    voucher_code = form_data.get('voucher_code')
    
    # Step 1: Validate scenario has a court complex
    if not scenario.default_court_complex:
        raise ValueError(
            f"Scenario '{scenario.display_name}' does not have a court complex configured. "
            "Please set the default court complex in the admin panel."
        )
    
    court_complex = scenario.default_court_complex
    
    # Step 2: Validate voucher if provided
    voucher_object = None
    if voucher_code:
        try:
            voucher_object = VoucherCode.objects.get(
                code=voucher_code,
                scenario=scenario,
                is_used=False
            )
        except VoucherCode.DoesNotExist:
            raise ValueError(f"Invalid or already used voucher code: {voucher_code}")
    
    # Step 3: Check available courts
    available_courts = Court.objects.filter(
        courtcomplex=court_complex,
        is_available=True
    ).order_by('id')[:num_courts]
    
    if available_courts.count() < num_courts:
        raise ValueError(
            f"Court complex '{court_complex.name}' only has {available_courts.count()} "
            f"available courts, but {num_courts} were requested."
        )
    
    # Step 4: Generate tournament dates (next day, 9am-6pm)
    tomorrow = timezone.now().date() + timedelta(days=1)
    start_date = timezone.make_aware(
        datetime.combine(tomorrow, datetime.min.time().replace(hour=9))
    )
    end_date = timezone.make_aware(
        datetime.combine(tomorrow, datetime.min.time().replace(hour=18))
    )
    
    # Step 5: Create the Tournament
    tournament_name = f"{scenario.display_name} {format_type.title()} - {start_date.strftime('%Y-%m-%d')}"
    
    tournament = Tournament.objects.create(
        name=tournament_name,
        description=f"Auto-generated {scenario.display_name} tournament",
        start_date=start_date,
        end_date=end_date,
        format="multi_stage",
        play_format="triplets" if format_type == "triples" else "doublets",
        is_active=True,
        max_participants=scenario.max_triples_players if format_type == "triples" else scenario.max_doubles_players,
        is_melee=True,
        melee_teams_generated=False,
        automation_status="idle"
    )
    
    # Step 6: Assign courts to tournament
    for court in available_courts:
        TournamentCourt.objects.create(
            tournament=tournament,
            court=court
        )
    
    # Step 7: Create SimpleTournament record
    simple_tournament = SimpleTournament.objects.create(
        tournament=tournament,
        scenario=scenario,
        format_type=format_type,
        uses_virtual_courts=False,
        num_courts=num_courts,
        court_complex=court_complex,
        voucher_used=voucher_object,
        auto_start_date=start_date,
        auto_end_date=end_date
    )
    
    # Step 8: Mark voucher as used
    if voucher_object:
        voucher_object.use_voucher(tournament)
    
    # Step 9: Create tournament stage
    Stage.objects.create(
        tournament=tournament,
        name="Main Stage",
        stage_number=1,
        stage_type=scenario.tournament_type,
        num_qualifiers=1,
        is_complete=False
    )
    
    return simple_tournament
