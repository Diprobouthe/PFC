from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, F, Q
from .models import Leaderboard, LeaderboardEntry, TeamStatistics, MatchStatistics
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
        })
    
    context = {
        'leaderboards': leaderboards,
    }
    return render(request, 'leaderboards/leaderboard_index.html', context)

# Removed login_required decorator
def tournament_leaderboard(request, tournament_id):
    """View for displaying tournament leaderboard"""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    
    # Get or create leaderboard
    leaderboard, created = Leaderboard.objects.get_or_create(tournament=tournament)
    
    # Update leaderboard entries
    update_tournament_leaderboard(tournament)
    
    # Get entries ordered by position
    entries = leaderboard.entries.all().order_by('position')
    
    context = {
        'tournament': tournament,
        'leaderboard': leaderboard,
        'entries': entries,
    }
    return render(request, 'leaderboards/tournament_leaderboard.html', context)

# Removed login_required decorator
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
    
    # Get tournament participation
    tournament_entries = LeaderboardEntry.objects.filter(team=team).select_related('leaderboard__tournament')
    
    context = {
        'team': team,
        'statistics': statistics,
        'recent_matches': recent_matches,
        'tournament_entries': tournament_entries,
    }
    return render(request, 'leaderboards/team_statistics.html', context)

# Removed login_required decorator
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
    """Update leaderboard entries for a tournament"""
    leaderboard, created = Leaderboard.objects.get_or_create(tournament=tournament)
    
    # Get all teams in the tournament
    teams = tournament.teams.all()
    
    # Process each team
    for team in teams:
        # Get matches where this team participated
        team_matches = Match.objects.filter(
            tournament=tournament,
            status='completed'
        ).filter(
            Q(team1=team) | Q(team2=team)
        )
        
        matches_played = team_matches.count()
        
        if matches_played == 0:
            continue
        
        # Calculate wins, losses, points scored and conceded
        matches_won = 0
        points_scored = 0
        points_conceded = 0
        
        for match in team_matches:
            if match.team1 == team:
                points_scored += match.team1_score or 0
                points_conceded += match.team2_score or 0
                if match.team1_score > match.team2_score:
                    matches_won += 1
            else:  # team2
                points_scored += match.team2_score or 0
                points_conceded += match.team1_score or 0
                if match.team2_score > match.team1_score:
                    matches_won += 1
        
        matches_lost = matches_played - matches_won
        
        # Update or create entry
        entry, created = LeaderboardEntry.objects.get_or_create(
            leaderboard=leaderboard,
            team=team,
            defaults={
                'position': 0,  # Will be updated later
                'matches_played': matches_played,
                'matches_won': matches_won,
                'matches_lost': matches_lost,
                'points_scored': points_scored,
                'points_conceded': points_conceded,
            }
        )
        
        if not created:
            entry.matches_played = matches_played
            entry.matches_won = matches_won
            entry.matches_lost = matches_lost
            entry.points_scored = points_scored
            entry.points_conceded = points_conceded
            entry.save()
    
    # Update positions
    entries = LeaderboardEntry.objects.filter(leaderboard=leaderboard).order_by('-matches_won', '-points_scored')
    
    for i, entry in enumerate(entries):
        entry.position = i + 1
        entry.save()

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
