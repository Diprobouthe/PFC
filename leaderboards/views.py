from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, F, Q
from .models import Leaderboard, LeaderboardEntry, TeamStatistics, MatchStatistics
from .swiss_ranking import is_swiss_tournament, get_swiss_rankings, get_traditional_rankings, get_stage_rankings, is_wtf_tournament
from .wtf_ranking import get_wtf_rankings, get_wtf_stage_rankings, update_wtf_statistics
from tournaments.models import Tournament
from teams.models import Team
from matches.models import Match

def leaderboard_index(request):
    """View for displaying all leaderboards"""
    tournaments = Tournament.objects.filter(is_active=True)
    leaderboards = []
    
    for tournament in tournaments:
        # Get or create leaderboard
        leaderboard, created = Leaderboard.objects.get_or_create(tournament=tournament)
        
        # Update leaderboard entries
        update_tournament_leaderboard(tournament)
        
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
    
    # Get or create leaderboard
    leaderboard, created = Leaderboard.objects.get_or_create(tournament=tournament)
    
    # Update leaderboard entries
    update_tournament_leaderboard(tournament)
    
    # Get entries ordered by position
    entries = leaderboard.entries.all().order_by('position')
    
    # Get Swiss-specific data if applicable
    swiss_data = None
    if is_swiss_tournament(tournament):
        swiss_rankings = get_swiss_rankings(tournament)
        swiss_data = {ranking['team'].id: ranking for ranking in swiss_rankings}
    
    # Get WTF-specific data if applicable
    wtf_data = None
    if is_wtf_tournament(tournament):
        # Update WTF statistics first
        update_wtf_statistics(tournament)
        wtf_rankings = get_wtf_rankings(tournament)
        wtf_data = {ranking['team'].id: ranking for ranking in wtf_rankings}
    
    context = {
        'tournament': tournament,
        'leaderboard': leaderboard,
        'entries': entries,
        'is_swiss': is_swiss_tournament(tournament),
        'is_wtf': is_wtf_tournament(tournament),
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

def update_tournament_leaderboard(tournament):
    """Update leaderboard entries for a tournament with Swiss system support"""
    leaderboard, created = Leaderboard.objects.get_or_create(tournament=tournament)
    
    # Clear existing entries to rebuild
    LeaderboardEntry.objects.filter(leaderboard=leaderboard).delete()
    
    # Use appropriate ranking system based on tournament format
    if is_swiss_tournament(tournament):
        # Use Swiss ranking with Buchholz tie-breaking
        rankings = get_swiss_rankings(tournament)
        
        # Create leaderboard entries with Swiss-specific data
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
        # Use WTF ranking with πετΑ Index
        # Update WTF statistics first
        update_wtf_statistics(tournament)
        rankings = get_wtf_rankings(tournament)
        
        # Create leaderboard entries with WTF-specific data
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
                # WTF-specific fields (if available in LeaderboardEntry model)
                swiss_points=ranking.get('swiss_points', 0),  # WTF still uses Swiss points
                buchholz_score=ranking.get('peta_index', 0.0),  # Store πετΑ Index in buchholz_score field
            )
    else:
        # Use traditional ranking for non-Swiss/WTF tournaments
        rankings = get_traditional_rankings(tournament)
        
        # Create leaderboard entries with traditional data
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
