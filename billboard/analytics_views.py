"""
Views for court complex usage analytics dashboard.
"""
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Sum, Avg, Max
from datetime import timedelta, datetime
from courts.models import CourtComplex
from billboard.analytics_models import (
    DailyUsageStats,
    HourlyUsageStats,
    CourtComplexUsageSnapshot
)
from billboard.analytics_utils import get_current_occupancy, get_peak_hours


def analytics_dashboard(request):
    """
    Main analytics dashboard showing overall usage statistics.
    """
    # Get all court complexes
    complexes = CourtComplex.objects.all()
    
    # Calculate date ranges
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # Get overall statistics
    context = {
        'complexes': complexes,
        'today': today,
    }
    
    # Get stats for each complex
    complex_stats = []
    for complex in complexes:
        current_occupancy = get_current_occupancy(complex)
        
        # Today's stats
        today_stats = DailyUsageStats.objects.filter(
            court_complex=complex,
            date=today
        ).first()
        
        # Week stats
        week_stats = DailyUsageStats.objects.filter(
            court_complex=complex,
            date__gte=week_ago
        ).aggregate(
            total_visitors=Sum('unique_visitors'),
            avg_visitors=Avg('unique_visitors'),
            peak_count=Max('peak_player_count')
        )
        
        complex_stats.append({
            'complex': complex,
            'current_occupancy': current_occupancy,
            'today_visitors': today_stats.unique_visitors if today_stats else 0,
            'week_total': week_stats['total_visitors'] or 0,
            'week_average': round(week_stats['avg_visitors'] or 0, 1),
            'week_peak': week_stats['peak_count'] or 0,
        })
    
    context['complex_stats'] = complex_stats
    
    return render(request, 'billboard/analytics_dashboard.html', context)


def complex_analytics(request, complex_id):
    """
    Detailed analytics for a specific court complex.
    """
    complex = get_object_or_404(CourtComplex, id=complex_id)
    
    # Date range (last 30 days)
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=30)
    
    # Get daily stats
    daily_stats = DailyUsageStats.objects.filter(
        court_complex=complex,
        date__gte=start_date,
        date__lte=end_date
    ).order_by('date')
    
    # Get hourly stats for heatmap (last 7 days)
    week_ago = end_date - timedelta(days=7)
    hourly_stats = HourlyUsageStats.objects.filter(
        court_complex=complex,
        date__gte=week_ago
    ).order_by('date', 'hour')
    
    # Get peak hours
    peak_hours = get_peak_hours(complex, days=30)
    
    context = {
        'complex': complex,
        'current_occupancy': get_current_occupancy(complex),
        'daily_stats': daily_stats,
        'hourly_stats': hourly_stats,
        'peak_hours': peak_hours[:5],  # Top 5 peak hours
        'start_date': start_date,
        'end_date': end_date,
    }
    
    return render(request, 'billboard/complex_analytics.html', context)


def analytics_api(request, complex_id):
    """
    API endpoint for fetching analytics data (for charts).
    """
    complex = get_object_or_404(CourtComplex, id=complex_id)
    
    # Get date range from query params
    days = int(request.GET.get('days', 30))
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days)
    
    # Get daily stats
    daily_stats = DailyUsageStats.objects.filter(
        court_complex=complex,
        date__gte=start_date,
        date__lte=end_date
    ).order_by('date')
    
    # Format data for charts
    data = {
        'labels': [stat.date.strftime('%Y-%m-%d') for stat in daily_stats],
        'visitors': [stat.unique_visitors for stat in daily_stats],
        'peak_counts': [stat.peak_player_count for stat in daily_stats],
        'complex_name': complex.name,
    }
    
    return JsonResponse(data)


def heatmap_api(request, complex_id):
    """
    API endpoint for heatmap data (hour × day grid).
    """
    complex = get_object_or_404(CourtComplex, id=complex_id)
    
    # Get last 4 weeks of data
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=28)
    
    # Get hourly stats
    hourly_stats = HourlyUsageStats.objects.filter(
        court_complex=complex,
        date__gte=start_date
    )
    
    # Build heatmap data: [day_of_week][hour] = avg_visitors
    heatmap = [[0 for _ in range(24)] for _ in range(7)]
    counts = [[0 for _ in range(24)] for _ in range(7)]
    
    for stat in hourly_stats:
        day_of_week = stat.date.weekday()  # 0=Monday, 6=Sunday
        hour = stat.hour
        heatmap[day_of_week][hour] += stat.unique_visitors
        counts[day_of_week][hour] += 1
    
    # Calculate averages
    for day in range(7):
        for hour in range(24):
            if counts[day][hour] > 0:
                heatmap[day][hour] = round(heatmap[day][hour] / counts[day][hour], 1)
    
    data = {
        'heatmap': heatmap,
        'days': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        'hours': list(range(24)),
        'complex_name': complex.name,
    }
    
    return JsonResponse(data)
