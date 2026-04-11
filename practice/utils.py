"""
Utility functions for practice session analysis and statistics.

Provides helper functions for calculating performance metrics,
generating insights, and analyzing shooting patterns.
"""

from datetime import timedelta
from django.utils import timezone
from typing import Dict, List, Optional, Tuple
from .models import PracticeSession, Shot


def calculate_session_summary(session: PracticeSession) -> Dict:
    """
    Calculate comprehensive summary statistics for a practice session.
    
    Args:
        session: PracticeSession instance
        
    Returns:
        Dictionary containing detailed session analysis
    """
    shots = Shot.objects.filter(session=session).order_by('sequence_number')
    
    if not shots.exists():
        return {
            'total_shots': 0,
            'hit_percentage': 0,
            'carreau_percentage': 0,
            'longest_streak': 0,
            'performance_note': 'No shots recorded in this session.',
            'duration': format_duration(session.duration),
            'first_miss_position': None,
            'shot_pattern': [],
            'consistency_score': 0
        }
    
    # Basic statistics
    total_shots = shots.count()
    
    # Determine practice type and calculate appropriate stats
    if session.practice_type == 'shooting':
        hits = shots.filter(outcome__in=['hit', 'petit_carreau', 'carreau']).count()
        petit_carreaux = shots.filter(outcome='petit_carreau').count()
        carreaux = shots.filter(outcome='carreau').count()
        hit_percentage = (hits / total_shots * 100) if total_shots > 0 else 0
        carreau_percentage = (carreaux / total_shots * 100) if total_shots > 0 else 0
    else:  # pointing practice
        perfects = shots.filter(outcome='perfect').count()
        petit_perfects = shots.filter(outcome='petit_perfect').count()
        goods = shots.filter(outcome='good').count()
        fairs = shots.filter(outcome='fair').count()
        fars = shots.filter(outcome='far').count()
        # For pointing, calculate success rate (perfect + petit_perfect + good + fair)
        hit_percentage = ((perfects + petit_perfects + goods + fairs) / total_shots * 100) if total_shots > 0 else 0
        carreau_percentage = (perfects / total_shots * 100) if total_shots > 0 else 0
    
    # Calculate streaks and patterns
    longest_streak = calculate_longest_hit_streak(shots)
    first_miss_position = find_first_miss_position(shots)
    shot_pattern = analyze_shot_pattern(shots)
    consistency_score = calculate_consistency_score(shots)
    
    # Generate performance insights
    performance_note = generate_performance_note(
        total_shots, hit_percentage, longest_streak, shot_pattern
    )
    
    return {
        'total_shots': total_shots,
        'hit_percentage': round(hit_percentage, 1),
        'carreau_percentage': round(carreau_percentage, 1),
        'longest_streak': longest_streak,
        'performance_note': performance_note,
        'duration': format_duration(session.duration),
        'first_miss_position': first_miss_position,
        'shot_pattern': shot_pattern,
        'consistency_score': consistency_score
    }


def calculate_longest_hit_streak(shots) -> int:
    """Calculate the longest consecutive successful shot streak in a session."""
    longest_streak = 0
    current_streak = 0
    success_outcomes = ['hit', 'petit_carreau', 'carreau', 'perfect', 'petit_perfect', 'good', 'fair']
    
    for shot in shots:
        if shot.outcome in success_outcomes:
            current_streak += 1
            longest_streak = max(longest_streak, current_streak)
        else:
            current_streak = 0
    
    return longest_streak


def find_first_miss_position(shots) -> Optional[int]:
    """Find the position of the first unsuccessful shot in the session."""
    unsuccessful_outcomes = ['miss', 'far']
    for shot in shots:
        if shot.outcome in unsuccessful_outcomes:
            return shot.sequence_number
    return None


def analyze_shot_pattern(shots) -> List[str]:
    """Analyze the pattern of shots to identify trends."""
    if shots.count() < 5:
        return []
    
    patterns = []
    shot_outcomes = [shot.outcome for shot in shots]
    
    # Check for strong start
    if all(outcome in ['hit', 'carreau'] for outcome in shot_outcomes[:3]):
        patterns.append('strong_start')
    
    # Check for strong finish
    if all(outcome in ['hit', 'carreau'] for outcome in shot_outcomes[-3:]):
        patterns.append('strong_finish')
    
    # Check for consistency (low variance in performance)
    hit_positions = [i for i, outcome in enumerate(shot_outcomes) if outcome in ['hit', 'carreau']]
    if len(hit_positions) > 3:
        gaps = [hit_positions[i+1] - hit_positions[i] for i in range(len(hit_positions)-1)]
        if max(gaps) - min(gaps) <= 2:  # Consistent spacing
            patterns.append('consistent')
    
    # Check for improvement trend
    first_half_hits = sum(1 for outcome in shot_outcomes[:len(shot_outcomes)//2] if outcome in ['hit', 'carreau'])
    second_half_hits = sum(1 for outcome in shot_outcomes[len(shot_outcomes)//2:] if outcome in ['hit', 'carreau'])
    
    first_half_rate = first_half_hits / (len(shot_outcomes)//2) if len(shot_outcomes) > 2 else 0
    second_half_rate = second_half_hits / (len(shot_outcomes) - len(shot_outcomes)//2) if len(shot_outcomes) > 2 else 0
    
    if second_half_rate > first_half_rate + 0.2:  # 20% improvement
        patterns.append('improving')
    elif first_half_rate > second_half_rate + 0.2:  # 20% decline
        patterns.append('declining')
    
    return patterns


def calculate_consistency_score(shots) -> float:
    """Calculate a consistency score based on shot distribution."""
    if shots.count() < 5:
        return 0.0
    
    shot_outcomes = [shot.outcome for shot in shots]
    
    # Calculate variance in performance across the session
    # Split into chunks and calculate hit rate for each
    chunk_size = max(3, shots.count() // 4)  # At least 3 shots per chunk
    chunks = []
    
    for i in range(0, len(shot_outcomes), chunk_size):
        chunk = shot_outcomes[i:i + chunk_size]
        if len(chunk) >= 2:  # Only consider chunks with at least 2 shots
            hit_rate = sum(1 for outcome in chunk if outcome in ['hit', 'carreau']) / len(chunk)
            chunks.append(hit_rate)
    
    if len(chunks) < 2:
        return 0.5  # Default score for short sessions
    
    # Calculate variance
    mean_rate = sum(chunks) / len(chunks)
    variance = sum((rate - mean_rate) ** 2 for rate in chunks) / len(chunks)
    
    # Convert to consistency score (lower variance = higher consistency)
    consistency_score = max(0.0, 1.0 - (variance * 4))  # Scale variance to 0-1
    
    return round(consistency_score, 2)


def generate_performance_note(total_shots: int, hit_percentage: float, 
                            longest_streak: int, patterns: List[str]) -> str:
    """Generate a personalized performance note based on session analysis."""
    
    notes = []
    
    # Performance level assessment
    if hit_percentage >= 85:
        notes.append("Excellent accuracy throughout the session!")
    elif hit_percentage >= 70:
        notes.append("Good shooting performance with room for improvement.")
    elif hit_percentage >= 50:
        notes.append("Decent session - focus on consistency in your next practice.")
    else:
        notes.append("Challenging session - consider working on fundamentals.")
    
    # Streak analysis
    if longest_streak >= total_shots * 0.6:  # 60% of shots in one streak
        notes.append(f"Outstanding consistency with a {longest_streak}-shot streak.")
    elif longest_streak >= 5:
        notes.append(f"Good momentum with a {longest_streak}-shot streak.")
    
    # Pattern-based insights
    if 'strong_start' in patterns and 'strong_finish' in patterns:
        notes.append("Maintained focus from start to finish.")
    elif 'strong_start' in patterns:
        notes.append("Started strong - work on maintaining concentration.")
    elif 'strong_finish' in patterns:
        notes.append("Finished strong - good recovery and adaptation.")
    
    if 'improving' in patterns:
        notes.append("Showed clear improvement during the session.")
    elif 'declining' in patterns:
        notes.append("Started well but lost focus - consider shorter sessions.")
    
    if 'consistent' in patterns:
        notes.append("Demonstrated excellent consistency throughout.")
    
    # Session length insights
    if total_shots >= 50:
        notes.append("Long session - great dedication to practice!")
    elif total_shots >= 20:
        notes.append("Good session length for skill development.")
    
    return " ".join(notes) if notes else "Keep practicing to improve your shooting skills!"


def format_duration(duration: timedelta) -> str:
    """Format a timedelta as a human-readable string."""
    if not duration:
        return "Unknown"
    
    total_seconds = int(duration.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    if hours > 0:
        return f"{hours}h {minutes}m"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"


def get_player_progress_summary(player_codename: str, days: int = 30) -> Dict:
    """
    Get a summary of player progress over the specified number of days.
    
    Args:
        player_codename: Player's codename
        days: Number of days to look back
        
    Returns:
        Dictionary containing progress analysis
    """
    cutoff_date = timezone.now() - timedelta(days=days)
    
    recent_sessions = PracticeSession.objects.filter(
        player_codename=player_codename,
        is_active=False,
        started_at__gte=cutoff_date
    ).order_by('started_at')
    
    if not recent_sessions.exists():
        return {
            'sessions_count': 0,
            'total_shots': 0,
            'average_hit_rate': 0,
            'improvement_trend': 'insufficient_data',
            'recommendation': 'Start practicing regularly to track your progress!'
        }
    
    # Calculate trend
    sessions_list = list(recent_sessions)
    if len(sessions_list) >= 3:
        # Compare first third vs last third
        first_third = sessions_list[:len(sessions_list)//3]
        last_third = sessions_list[-len(sessions_list)//3:]
        
        first_avg = sum(s.hit_percentage for s in first_third) / len(first_third)
        last_avg = sum(s.hit_percentage for s in last_third) / len(last_third)
        
        if last_avg > first_avg + 5:  # 5% improvement
            trend = 'improving'
        elif first_avg > last_avg + 5:  # 5% decline
            trend = 'declining'
        else:
            trend = 'stable'
    else:
        trend = 'insufficient_data'
    
    # Generate recommendation
    total_shots = sum(s.total_shots for s in sessions_list)
    avg_hit_rate = sum(s.hit_percentage for s in sessions_list) / len(sessions_list)
    
    if trend == 'improving':
        recommendation = "Great progress! Keep up the regular practice."
    elif trend == 'declining':
        recommendation = "Consider shorter, more focused sessions to regain consistency."
    elif avg_hit_rate >= 75:
        recommendation = "Excellent accuracy! Try challenging yourself with longer distances."
    elif avg_hit_rate >= 50:
        recommendation = "Good foundation. Focus on consistency in your practice routine."
    else:
        recommendation = "Work on fundamentals and practice regularly to improve accuracy."
    
    return {
        'sessions_count': len(sessions_list),
        'total_shots': total_shots,
        'average_hit_rate': round(avg_hit_rate, 1),
        'improvement_trend': trend,
        'recommendation': recommendation
    }
