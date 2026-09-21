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
    """View for displaying all leaderboards."""
    tournaments = Tournament.objects.filter(is_active=True)
    leaderboards = []
    for tournament in tournaments:
        leaderboard, created = Leaderboard.objects.get_or_create(tournament=tournament)
        # Fresh cached standings require no write. A stale rebuild is serialized.
        update_tournament_leaderboard(tournament)
        top_entries = leaderboard.entries.all().order_by('position')[:3]
        leaderboards.append({
            'tournament': tournament,
            'leaderboard': leaderboard,
            'top_entries': top_entries,
            'is_swiss': is_swiss_tournament(tournament),
            'is_wtf': is_wtf_tournament(tournament),
        })
    return render(request, 'leaderboards/leaderboard_index.html', {
        'leaderboards': leaderboards,
    })


def tournament_leaderboard(request, tournament_id):
    """Display cached tournament standings, rebuilding only when results change."""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    leaderboard, created = Leaderboard.objects.get_or_create(tournament=tournament)
    update_tournament_leaderboard(tournament)
    entries = leaderboard.entries.all().order_by('position')

    # The template displays persisted entry fields. Calling get_swiss_rankings
    # here caused another full Swiss/Buchholz write on every ordinary GET.
    swiss_data = None

    wtf_data = None
    if is_wtf_tournament(tournament):
        # Preserve the existing WTF display context; its writes are now only
        # avoidable when the WTF ranking implementation is separately audited.
        update_wtf_statistics(tournament)
        wtf_rankings = get_wtf_rankings(tournament)
        wtf_data = {ranking['team'].id: ranking for ranking in wtf_rankings}

    is_multistage = is_multistage_team_tournament(tournament)
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
    """View for displaying stage-specific leaderboard."""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    if tournament.format != 'multi_stage':
        return redirect('leaderboards:tournament_leaderboard', tournament_id=tournament_id)
    try:
        stage = tournament.stages.get(stage_number=stage_number)
    except Exception:
        return redirect('leaderboards:tournament_leaderboard', tournament_id=tournament_id)
    rankings = get_stage_rankings(tournament, stage_number)
    context = {
        'tournament': tournament,
        'stage': stage,
        'rankings': rankings,
        'is_swiss': stage.format in ['swiss', 'smart_swiss'],
    }
    return render(request, 'leaderboards/stage_leaderboard.html', context)


def team_statistics(request, team_id):
    """View for displaying team statistics."""
    team = get_object_or_404(Team, id=team_id)
    statistics, created = TeamStatistics.objects.get_or_create(team=team)
    update_team_statistics(team)
    recent_matches = Match.objects.filter(
        Q(team1=team) | Q(team2=team),
        status='completed'
    ).order_by('-end_time')[:10]
    tournament_entries = []
    leaderboard_entries = LeaderboardEntry.objects.filter(team=team).select_related('leaderboard__tournament')
    for entry in leaderboard_entries:
        tournament = entry.leaderboard.tournament
        entry_data = {
            'tournament': tournament,
            'entry': entry,
            'is_swiss': is_swiss_tournament(tournament),
        }
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
    match = get_object_or_404(Match, id=match_id)
    statistics, created = MatchStatistics.objects.get_or_create(match=match)
    context = {'match': match, 'statistics': statistics}
    return render(request, 'leaderboards/match_statistics.html', context)


def update_tournament_leaderboard(tournament):
    """Rebuild only stale standings under one lock per tournament leaderboard.

    Both the deletion and insertion are atomic. Concurrent GETs cannot race to
    insert the same (leaderboard, team) row; ordinary GETs do not rebuild a
    fresh table. Other explicit callers still refresh after Match changes.
    """
    leaderboard, created = Leaderboard.objects.get_or_create(tournament=tournament)
    with transaction.atomic():
        leaderboard = Leaderboard.objects.select_for_update().get(pk=leaderboard.pk)
        newest_match_change = (
            Match.objects.filter(tournament=tournament)
            .order_by('-updated_at')
            .values_list('updated_at', flat=True)
            .first()
        )
        existing_entries = LeaderboardEntry.objects.filter(leaderboard=leaderboard)
        if existing_entries.exists() and (
            newest_match_change is None or newest_match_change <= leaderboard.last_updated
        ):
            return

        # The lock prevents simultaneous delete/recreate races. An exception
        # rolls back the complete replacement and leaves the old table intact.
        existing_entries.delete()
        if is_multistage_team_tournament(tournament):
            rankings = get_global_multistage_rankings(tournament)
            for ranking in rankings:
                LeaderboardEntry.objects.create(
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
                )
        elif is_swiss_tournament(tournament):
            rankings = get_swiss_rankings(tournament)
            for ranking in rankings:
                LeaderboardEntry.objects.create(
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
                )
        elif is_wtf_tournament(tournament):
            update_wtf_statistics(tournament)
            rankings = get_wtf_rankings(tournament)
            for ranking in rankings:
                LeaderboardEntry.objects.create(
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
                )
        else:
            rankings = get_traditional_rankings(tournament)
            for ranking in rankings:
                LeaderboardEntry.objects.create(
                    leaderboard=leaderboard,
                    team=ranking['team'],
                    position=ranking['position'],
                    matches_played=ranking['matches_played'],
                    matches_won=ranking['matches_won'],
                    matches_lost=ranking['matches_lost'],
                    points_scored=ranking['points_scored'],
                    points_conceded=ranking['points_conceded'],
                )
        leaderboard.save(update_fields=['last_updated'])


def update_team_statistics(team):
    """Update overall statistics for a team."""
    statistics, created = TeamStatistics.objects.get_or_create(team=team)
    team_matches = Match.objects.filter(status='completed').filter(
        Q(team1=team) | Q(team2=team)
    )
    total_matches_played = team_matches.count()
    if total_matches_played == 0:
        return
    total_matches_won = 0
    total_points_scored = 0
    total_points_conceded = 0
    for match in team_matches:
        if match.team1 == team:
            total_points_scored += match.team1_score or 0
            total_points_conceded += match.team2_score or 0
            if match.team1_score > match.team2_score:
                total_matches_won += 1
        else:
            total_points_scored += match.team2_score or 0
            total_points_conceded += match.team1_score or 0
            if match.team2_score > match.team1_score:
                total_matches_won += 1
    total_matches_lost = total_matches_played - total_matches_won
    tournaments_participated = Tournament.objects.filter(teams=team).count()
    tournaments_won = LeaderboardEntry.objects.filter(team=team, position=1).count()
    statistics.total_matches_played = total_matches_played
    statistics.total_matches_won = total_matches_won
    statistics.total_matches_lost = total_matches_lost
    statistics.total_points_scored = total_points_scored
    statistics.total_points_conceded = total_points_conceded
    statistics.tournaments_participated = tournaments_participated
    statistics.tournaments_won = tournaments_won
    statistics.save()
