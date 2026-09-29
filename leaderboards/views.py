from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum, Count, F, Q
from .models import Leaderboard, LeaderboardEntry, TeamStatistics, MatchStatistics
from .swiss_ranking import (
    is_swiss_tournament, get_swiss_rankings, get_traditional_rankings,
    get_stage_rankings, is_wtf_tournament,
    is_multistage_team_tournament, get_global_multistage_rankings,
)
from .wtf_ranking import get_wtf_rankings, get_wtf_stage_rankings, update_wtf_statistics
from tournaments.models import Tournament
from teams.models import Team
from matches.models import Match

def leaderboard_index(request):
    """View for displaying all leaderboards"""
    tournaments = Tournament.objects.filter(is_active=True)
    leaderboards = []
    
    for tournament in tournaments:
        # Public GET is strictly read-only. Round publication creates or
        # refreshes this projection; an unopened/new tournament simply has no
        # published leaderboard yet.
        leaderboard = Leaderboard.objects.filter(tournament=tournament).first()
        if leaderboard is None:
            continue
        
        # Get top entries
        top_entries = leaderboard.entries.all().order_by('position')[:3]
        
        leaderboards.append({
            'tournament': tournament,
            'leaderboard': leaderboard,
            'top_entries': top_entries,
            'is_swiss': is_swiss_tournament(tournament),
            'is_wtf': is_wtf_tournament(tournament),
        })
    
    context = {
        'leaderboards': leaderboards,
    }
    return render(request, 'leaderboards/leaderboard_index.html', context)

def tournament_leaderboard(request, tournament_id):
    """View for displaying tournament leaderboard with Swiss support"""
    tournament = get_object_or_404(Tournament, id=tournament_id)

    # A viewer never creates, locks, deletes, or rebuilds shared state.
    leaderboard = Leaderboard.objects.filter(tournament=tournament).first()

    # Get entries ordered by position
    entries = (
        leaderboard.entries.all().order_by('position')
        if leaderboard is not None
        else LeaderboardEntry.objects.none()
    )

    # Get Swiss-specific data if applicable
    swiss_data = None
    if is_swiss_tournament(tournament):
        swiss_data = {
            entry.team_id: {
                'swiss_points': entry.swiss_points,
                'buchholz_score': entry.buchholz_score,
            }
            for entry in entries
        }

    # Get WTF-specific data if applicable
    wtf_data = None
    if is_wtf_tournament(tournament):
        wtf_data = {
            entry.team_id: {
                'swiss_points': entry.swiss_points,
                'peta_index': entry.buchholz_score,
            }
            for entry in entries
        }

    # Determine if this is a multi-stage team tournament (not mêlée)
    is_multistage = is_multistage_team_tournament(tournament)

    # Build stage summary for multi-stage tournaments
    stages_summary = []
    if is_multistage:
        for stage in tournament.stages.order_by('stage_number'):
            stages_summary.append({
                'stage_number': stage.stage_number,
                'name': stage.name or f'Stage {stage.stage_number}',
                'format': stage.get_format_display(),
                'num_qualifiers': stage.num_qualifiers,
            })

    context = {
        'tournament': tournament,
        'leaderboard': leaderboard,
        'entries': entries,
        'is_swiss': is_swiss_tournament(tournament),
        'is_wtf': is_wtf_tournament(tournament),
        'is_multistage': is_multistage,
        'stages_summary': stages_summary,
        'swiss_data': swiss_data,
        'wtf_data': wtf_data,
    }
    return render(request, 'leaderboards/tournament_leaderboard.html', context)

def stage_leaderboard(request, tournament_id, stage_number):
    """View for displaying stage-specific leaderboard"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    if tournament.format != 'multi_stage':
        return redirect('leaderboards:tournament_leaderboard', tournament_id=tournament_id)
    
    try:
        stage = tournament.stages.get(stage_number=stage_number)
    except:
        return redirect('leaderboards:tournament_leaderboard', tournament_id=tournament_id)
    
    # Get stage rankings
    rankings = get_stage_rankings(tournament, stage_number)
    
    context = {
        'tournament': tournament,
        'stage': stage,
        'rankings': rankings,
        'is_swiss': stage.format in ['swiss', 'smart_swiss'],
    }
    return render(request, 'leaderboards/stage_leaderboard.html', context)

def team_statistics(request, team_id):
    """View for displaying team statistics"""
    team = get_object_or_404(Team, id=team_id)
    
    # Get or create team statistics
    statistics, created = TeamStatistics.objects.get_or_create(team=team)
    
    # Update statistics
    update_team_statistics(team)
    
    # Get recent matches
    recent_matches = Match.objects.filter(
        Q(team1=team) | Q(team2=team),
        status='completed'
    ).order_by('-end_time')[:10]
    
    # Get tournament participation with Swiss data
    tournament_entries = []
    leaderboard_entries = LeaderboardEntry.objects.filter(team=team).select_related('leaderboard__tournament')
    
    for entry in leaderboard_entries:
        tournament = entry.leaderboard.tournament
        entry_data = {
            'tournament': tournament,
            'entry': entry,
            'is_swiss': is_swiss_tournament(tournament),
        }
        
        # Add Swiss-specific data if applicable
        if entry_data['is_swiss']:
            try:
                from tournaments.models import TournamentTeam
                tournament_team = TournamentTeam.objects.get(tournament=tournament, team=team)
                entry_data['swiss_points'] = tournament_team.swiss_points
                entry_data['buchholz_score'] = tournament_team.buchholz_score
            except TournamentTeam.DoesNotExist:
                pass
        
        tournament_entries.append(entry_data)
    
    context = {
        'team': team,
        'statistics': statistics,
        'recent_matches': recent_matches,
        'tournament_entries': tournament_entries,
    }
    return render(request, 'leaderboards/team_statistics.html', context)

def match_statistics(request, match_id):
    """View for displaying match statistics"""
    match = get_object_or_404(Match, id=match_id)
    
    # Get or create match statistics
    statistics, created = MatchStatistics.objects.get_or_create(match=match)
    
    context = {
        'match': match,
        'statistics': statistics,
    }
    return render(request, 'leaderboards/match_statistics.html', context)

def publish_tournament_leaderboard(tournament):
    """Publish a tournament leaderboard from a protected Round transition.

    Only lifecycle/projection code calls this mutator. Public GET handlers read
    the last completed Round's projection without taking write locks.
    """
    with transaction.atomic():
        locked_tournament = Tournament.objects.select_for_update(of=("self",)).get(
            pk=tournament.pk
        )
        leaderboard, _ = Leaderboard.objects.get_or_create(tournament=locked_tournament)
        Leaderboard.objects.select_for_update(of=("self",)).get(pk=leaderboard.pk)
        return _rebuild_tournament_leaderboard_locked(locked_tournament, leaderboard)


# Compatibility for explicit administration code. It must not be called from a
# normal GET view; new lifecycle code uses the clearer publication name above.
update_tournament_leaderboard = publish_tournament_leaderboard


def _rebuild_tournament_leaderboard_locked(tournament, leaderboard):
    """Replace one tournament's published projection with batched writes."""
    LeaderboardEntry.objects.filter(leaderboard=leaderboard).delete()
    entries_to_create = []

    if is_multistage_team_tournament(tournament):
        rankings = get_global_multistage_rankings(tournament)
        for ranking in rankings:
            entries_to_create.append(LeaderboardEntry(
                leaderboard=leaderboard,
                team=ranking['team'],
                position=ranking['position'],
                matches_played=ranking['matches_played'],
                matches_won=ranking['matches_won'],
                matches_lost=ranking['matches_lost'],
                points_scored=ranking['points_scored'],
                points_conceded=ranking['points_conceded'],
                swiss_points=ranking.get('swiss_points', 0),
                buchholz_score=ranking.get('buchholz_score', 0.0),
                stage_reached=ranking.get('stage_reached', 1),
                tournament_status=ranking.get('tournament_status', 'active'),
            ))
    elif is_swiss_tournament(tournament):
        for ranking in get_swiss_rankings(tournament):
            entries_to_create.append(LeaderboardEntry(
                leaderboard=leaderboard,
                team=ranking['team'],
                position=ranking['position'],
                matches_played=ranking['matches_played'],
                matches_won=ranking['matches_won'],
                matches_lost=ranking['matches_lost'],
                points_scored=ranking['points_scored'],
                points_conceded=ranking['points_conceded'],
                swiss_points=ranking.get('swiss_points', 0),
                buchholz_score=ranking.get('buchholz_score', 0.0),
            ))
    elif is_wtf_tournament(tournament):
        update_wtf_statistics(tournament)
        for ranking in get_wtf_rankings(tournament):
            entries_to_create.append(LeaderboardEntry(
                leaderboard=leaderboard,
                team=ranking['team'],
                position=ranking['position'],
                matches_played=ranking['matches_played'],
                matches_won=ranking['matches_won'],
                matches_lost=ranking['matches_lost'],
                points_scored=ranking['points_scored'],
                points_conceded=ranking['points_conceded'],
                swiss_points=ranking.get('swiss_points', 0),
                buchholz_score=ranking.get('peta_index', 0.0),
            ))
    else:
        for ranking in get_traditional_rankings(tournament):
            entries_to_create.append(LeaderboardEntry(
                leaderboard=leaderboard,
                team=ranking['team'],
                position=ranking['position'],
                matches_played=ranking['matches_played'],
                matches_won=ranking['matches_won'],
                matches_lost=ranking['matches_lost'],
                points_scored=ranking['points_scored'],
                points_conceded=ranking['points_conceded'],
            ))

    LeaderboardEntry.objects.bulk_create(entries_to_create, batch_size=250)
    return leaderboard

def update_team_statistics(team):
    """Update overall statistics for a team"""
    statistics, created = TeamStatistics.objects.get_or_create(team=team)
    
    # Get all completed matches for this team
    team_matches = Match.objects.filter(
        status='completed'
    ).filter(
        Q(team1=team) | Q(team2=team)
    )
    
    total_matches_played = team_matches.count()
    
    if total_matches_played == 0:
        return
    
    # Calculate wins, losses, points scored and conceded
    total_matches_won = 0
    total_points_scored = 0
    total_points_conceded = 0
    
    for match in team_matches:
        if match.team1 == team:
            total_points_scored += match.team1_score or 0
            total_points_conceded += match.team2_score or 0
            if match.team1_score > match.team2_score:
                total_matches_won += 1
        else:  # team2
            total_points_scored += match.team2_score or 0
            total_points_conceded += match.team1_score or 0
            if match.team2_score > match.team1_score:
                total_matches_won += 1
    
    total_matches_lost = total_matches_played - total_matches_won
    
    # Count tournaments participated in
    tournaments_participated = Tournament.objects.filter(
        teams=team
    ).count()
    
    # Count tournaments won (simplified - in a real system this would be more complex)
    tournaments_won = LeaderboardEntry.objects.filter(
        team=team,
        position=1
    ).count()
    
    # Update statistics
    statistics.total_matches_played = total_matches_played
    statistics.total_matches_won = total_matches_won
    statistics.total_matches_lost = total_matches_lost
    statistics.total_points_scored = total_points_scored
    statistics.total_points_conceded = total_points_conceded
    statistics.tournaments_participated = tournaments_participated
    statistics.tournaments_won = tournaments_won
    statistics.save()
