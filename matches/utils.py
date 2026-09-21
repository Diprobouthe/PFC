from django.utils.translation import gettext as _
from django.db import transaction
from django.db.models import Q
import logging
from courts.models import Court

logger = logging.getLogger(__name__)


def detect_match_type(team1_players, team2_players):
    """Return the match type and player counts for the two sides."""
    team1_count = len(team1_players)
    team2_count = len(team2_players)
    if team1_count != team2_count:
        return 'mixed', team1_count, team2_count
    if team1_count == 1:
        return 'tete_a_tete', team1_count, team2_count
    if team1_count == 2:
        return 'doublet', team1_count, team2_count
    if team1_count == 3:
        return 'triplet', team1_count, team2_count
    logger.warning('Unexpected player count: %s vs %s', team1_count, team2_count)
    return 'unknown', team1_count, team2_count


def validate_match_type(match_type, team1_count, team2_count, tournament):
    """Validate the match format against the tournament's allowed formats."""
    config = getattr(tournament, 'allowed_match_types', None)
    if not config:
        return True, None
    if match_type == 'mixed' and not config.get('allow_mixed', False):
        return False, _("Mixed matches are not allowed in this tournament. Both teams must have the same number of players. Team 1 has {} players, Team 2 has {} players.").format(team1_count, team2_count)
    allowed_types = config.get('allowed_match_types', [])
    if not allowed_types or match_type in allowed_types:
        return True, None
    if match_type == 'doublet':
        error_message = _("Doublet matches (2 players per team) are not allowed in this tournament. Please select {} players per team.").format(get_required_player_count(allowed_types))
    elif match_type == 'triplet':
        error_message = _("Triplet matches (3 players per team) are not allowed in this tournament. Please select {} players per team.").format(get_required_player_count(allowed_types))
    elif match_type == 'tete_a_tete':
        error_message = _("Tête-à-tête matches (1 player per team) are not allowed in this tournament. Please select {} players per team.").format(get_required_player_count(allowed_types))
    else:
        error_message = _("This match format ({}) is not allowed in this tournament. Allowed formats: {}").format(
            get_match_type_display(match_type),
            ", ".join([get_match_type_display(t) for t in allowed_types])
        )
    return False, error_message


def get_required_player_count(allowed_types):
    if len(allowed_types) == 1:
        if 'triplet' in allowed_types:
            return 3
        if 'doublet' in allowed_types:
            return 2
        if 'tete_a_tete' in allowed_types:
            return 1
    return 'the correct number of'


def get_match_type_display(match_type):
    display_names = {
        'doublet': _("Doublet (2 players)"),
        'triplet': _("Triplet (3 players)"),
        'tete_a_tete': _("Tête-à-tête (1 player)"),
        'mixed': _("Mixed format"),
        'unknown': _("Unknown format"),
    }
    return display_names.get(match_type, match_type)


def auto_assign_court(match):
    """Assign one court without racing another tournament Match activation.

    The Match is locked first (as in match_activate), then one available Court
    is row-locked before either object is updated. The two writes commit or
    roll back together. This does not reserve a venue for an entire tournament.
    """
    from .models import Match

    try:
        with transaction.atomic():
            current = (
                Match.objects.select_for_update()
                .select_related('tournament', 'poule')
                .get(pk=match.pk)
            )
            if current.court_id:
                court = Court.objects.get(pk=current.court_id)
                match.court = court
                return court

            court_ids = None
            if current.poule_id:
                pool = list(current.poule.courts.values_list('id', flat=True))
                if pool:
                    court_ids = pool

            if court_ids is None:
                pool = list(
                    current.tournament.tournamentcourt_set.values_list('court_id', flat=True)
                )
                if pool:
                    court_ids = pool
                else:
                    logger.info(
                        'No courts assigned to tournament %s; using general court pool',
                        current.tournament_id,
                    )

            # A waiting-validation match is still using its court. A match
            # awaiting its second activation can also have a pre-assigned court.
            occupied = Match.objects.filter(court__isnull=False).filter(
                Q(status__in=('active', 'waiting_validation'))
                | Q(status='pending_verification', waiting_for_court=False)
            ).exclude(pk=current.pk).values('court_id')

            choices = Court.objects.filter(is_available=True).exclude(pk__in=occupied)
            if court_ids is not None:
                choices = choices.filter(pk__in=court_ids)

            # PostgreSQL SKIP LOCKED lets a second simultaneous activation
            # move to the next court instead of making the same selection.
            court = (
                choices.select_for_update(skip_locked=True)
                .order_by('number', 'pk')
                .first()
            )
            if court is None:
                logger.info('No free court for match %s', current.pk)
                return None

            court.is_available = False
            court.save(update_fields=['is_available'])
            current.court = court
            current.save(update_fields=['court'])
            match.court = court
            logger.info('Assigned and reserved court %s for match %s', court.pk, current.pk)
            return court
    except Exception:
        logger.exception('auto_assign_court failed for match %s', match.pk)
        return None


def get_court_assignment_status(match):
    if match.court:
        return _("The court %(court_name)s has been assigned to your match.") % {
            'court_name': match.court.name,
        }
    if match.waiting_for_court:
        return _("Your match is waiting for a court to become available.")
    return _("No court has been assigned to your match yet.")
