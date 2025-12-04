# Game Timer System Design

## Date: December 3, 2025

## Overview
Implement a timer system for petanque matches with admin-configurable time limits. The timer serves as a reminder (not a hard constraint) and supports the "cosone" rule where additional rounds can be played after time expires.

---

## Requirements

### Functional Requirements
1. **Admin Configuration**: Admin can set time limit for each game (in minutes)
2. **Countdown Start**: Timer starts when BOTH teams have activated the match
3. **Visual Display**: Players see countdown timer during active matches
4. **Reminder Only**: Players can submit scores after time expires (no hard constraint)
5. **Cosone Support**: After time expires, players can play another round
6. **Flexible**: Not all games need timers (optional field)

### User Stories
- **As an admin**, I want to set a time limit for each match so players know how long they have
- **As a player**, I want to see how much time remains in my match so I can pace the game
- **As a player**, I want to be notified when time expires but still be able to finish the current round
- **As a player**, I want to play a cosone (additional round) after time expires if needed

---

## Current System Analysis

### Match Activation Flow
1. **Team 1 initiates** → Match status: `"pending_verification"`
2. **Team 2 validates** → Match status: `"active"`, `start_time` set to `timezone.now()`
3. **Score submitted** → Match status: `"waiting_validation"`
4. **Score validated** → Match status: `"completed"`, `end_time` set

### Key Code Locations

**Match Model** (`matches/models.py`):
- Line 40: `start_time = models.DateTimeField(null=True, blank=True)`
- Line 41: `end_time = models.DateTimeField(null=True, blank=True)`
- Line 42: `duration = models.DurationField(null=True, blank=True)`

**Match Activation** (`matches/views.py`, line 284-287):
```python
if court:
    match.status = "active"
    match.start_time = timezone.now()  # ← Timer should start here
    match.waiting_for_court = False
```

---

## Database Schema Changes

### Add to Match Model

```python
# Timer configuration (admin-set)
time_limit_minutes = models.PositiveIntegerField(
    null=True, 
    blank=True,
    help_text="Time limit in minutes (optional). Timer starts when both teams activate."
)

# Timer state tracking
timer_expired = models.BooleanField(
    default=False,
    help_text="Whether the time limit has been reached"
)

timer_expired_at = models.DateTimeField(
    null=True,
    blank=True,
    help_text="When the timer expired (if applicable)"
)
```

### Migration Required
- Create migration: `python manage.py makemigrations matches`
- Migration will add 3 new fields to Match model
- All existing matches: `time_limit_minutes=NULL` (no timer)

---

## Backend Implementation

### 1. Model Properties

Add to `Match` model:

```python
@property
def time_remaining_seconds(self):
    """Calculate remaining time in seconds. Returns None if no timer set."""
    if not self.time_limit_minutes or not self.start_time:
        return None
    
    if self.status != "active":
        return None
    
    # Calculate elapsed time
    elapsed = timezone.now() - self.start_time
    total_seconds = self.time_limit_minutes * 60
    remaining = total_seconds - elapsed.total_seconds()
    
    return max(0, remaining)  # Never negative

@property
def time_remaining_display(self):
    """Human-readable time remaining (MM:SS format)."""
    remaining = self.time_remaining_seconds
    if remaining is None:
        return None
    
    minutes = int(remaining // 60)
    seconds = int(remaining % 60)
    return f"{minutes:02d}:{seconds:02d}"

@property
def is_time_expired(self):
    """Check if timer has expired."""
    remaining = self.time_remaining_seconds
    if remaining is None:
        return False
    return remaining == 0
```

### 2. Admin Interface

Update `matches/admin.py`:

```python
@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'team1', 'team2', 'tournament', 
        'status', 'time_limit_minutes', 'timer_status'
    ]
    
    list_editable = ['time_limit_minutes']  # Quick edit in list view
    
    fieldsets = [
        ('Match Info', {
            'fields': ['tournament', 'team1', 'team2', 'court']
        }),
        ('Timer Configuration', {
            'fields': ['time_limit_minutes'],
            'description': 'Set time limit in minutes (optional). Timer starts when both teams activate.'
        }),
        ('Status', {
            'fields': ['status', 'start_time', 'end_time', 'duration']
        }),
    ]
    
    def timer_status(self, obj):
        """Display timer status in admin list."""
        if not obj.time_limit_minutes:
            return "No timer"
        if obj.status != "active":
            return "Not started"
        remaining = obj.time_remaining_display
        if obj.is_time_expired:
            return f"⏰ EXPIRED"
        return f"⏱️ {remaining}"
    timer_status.short_description = "Timer"
```

### 3. Timer Expiration Check

Add background task or view helper:

```python
def check_and_mark_expired_timers():
    """Check active matches and mark timers as expired if needed."""
    active_matches = Match.objects.filter(
        status="active",
        time_limit_minutes__isnull=False,
        timer_expired=False
    )
    
    for match in active_matches:
        if match.is_time_expired and not match.timer_expired:
            match.timer_expired = True
            match.timer_expired_at = timezone.now()
            match.save(update_fields=['timer_expired', 'timer_expired_at'])
            
            # Could trigger notification here
            logger.info(f"Timer expired for match {match.id}")
```

---

## Frontend Implementation

### 1. Match Detail Page

Add timer display to `matches/match_detail.html`:

```django
{% if match.time_limit_minutes and match.status == 'active' %}
<div class="card mb-3" id="timer-card">
    <div class="card-body text-center">
        {% if match.is_time_expired %}
            <h4 class="text-warning mb-2">
                <i class="bi bi-alarm"></i> Time Expired
            </h4>
            <p class="text-muted mb-0">
                You may continue playing or play a cosone (additional round)
            </p>
        {% else %}
            <h4 class="mb-2">
                <i class="bi bi-clock"></i> Time Remaining
            </h4>
            <div class="display-4 fw-bold" id="timer-display">
                {{ match.time_remaining_display }}
            </div>
            <div class="progress mt-3" style="height: 10px;">
                <div class="progress-bar bg-success" 
                     id="timer-progress"
                     role="progressbar" 
                     style="width: 100%;">
                </div>
            </div>
        {% endif %}
    </div>
</div>
{% endif %}
```

### 2. Live Countdown JavaScript

Add to match detail template:

```javascript
<script>
document.addEventListener('DOMContentLoaded', function() {
    {% if match.time_limit_minutes and match.status == 'active' and not match.is_time_expired %}
    
    // Initial values from server
    let remainingSeconds = {{ match.time_remaining_seconds|default:0 }};
    const totalSeconds = {{ match.time_limit_minutes }} * 60;
    
    function updateTimer() {
        if (remainingSeconds <= 0) {
            // Timer expired - reload page to show expired state
            location.reload();
            return;
        }
        
        // Update display
        const minutes = Math.floor(remainingSeconds / 60);
        const seconds = remainingSeconds % 60;
        const display = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
        
        document.getElementById('timer-display').textContent = display;
        
        // Update progress bar
        const percentage = (remainingSeconds / totalSeconds) * 100;
        const progressBar = document.getElementById('timer-progress');
        progressBar.style.width = percentage + '%';
        
        // Change color as time runs out
        if (percentage < 20) {
            progressBar.className = 'progress-bar bg-danger';
        } else if (percentage < 50) {
            progressBar.className = 'progress-bar bg-warning';
        } else {
            progressBar.className = 'progress-bar bg-success';
        }
        
        // Decrement
        remainingSeconds--;
    }
    
    // Update every second
    setInterval(updateTimer, 1000);
    
    {% endif %}
});
</script>
```

### 3. Timer Badge in Match List

Add to `matches/match_list.html`:

```django
{% if match.time_limit_minutes %}
    {% if match.status == 'active' %}
        {% if match.is_time_expired %}
            <span class="badge bg-warning">
                <i class="bi bi-alarm"></i> Time Expired
            </span>
        {% else %}
            <span class="badge bg-info">
                <i class="bi bi-clock"></i> {{ match.time_remaining_display }}
            </span>
        {% endif %}
    {% else %}
        <span class="badge bg-secondary">
            <i class="bi bi-clock"></i> {{ match.time_limit_minutes }} min
        </span>
    {% endif %}
{% endif %}
```

---

## API Endpoint (Optional)

For real-time updates without page reload:

```python
# matches/views.py
from django.http import JsonResponse

def match_timer_status(request, match_id):
    """API endpoint for timer status."""
    match = get_object_or_404(Match, id=match_id)
    
    if not match.time_limit_minutes:
        return JsonResponse({'has_timer': False})
    
    return JsonResponse({
        'has_timer': True,
        'time_limit_minutes': match.time_limit_minutes,
        'remaining_seconds': match.time_remaining_seconds,
        'remaining_display': match.time_remaining_display,
        'is_expired': match.is_time_expired,
        'status': match.status,
    })
```

```javascript
// Fetch timer status every 10 seconds
setInterval(function() {
    fetch(`/matches/{{ match.id }}/timer-status/`)
        .then(response => response.json())
        .then(data => {
            if (data.is_expired) {
                location.reload();
            }
            // Update UI with fresh data
        });
}, 10000);
```

---

## User Experience Flow

### Scenario 1: Match with Timer

1. **Admin creates match** → Sets `time_limit_minutes = 45`
2. **Team 1 activates** → Match status: `pending_verification` (timer not started)
3. **Team 2 validates** → Match status: `active`, `start_time` set, **timer starts**
4. **Players see countdown** → "⏱️ 44:32" with green progress bar
5. **20 minutes remaining** → Progress bar turns yellow
6. **5 minutes remaining** → Progress bar turns red
7. **Timer expires** → "⏰ Time Expired - You may continue or play a cosone"
8. **Players submit score** → Allowed regardless of timer status

### Scenario 2: Match without Timer

1. **Admin creates match** → Leaves `time_limit_minutes = NULL`
2. **Match activates normally** → No timer display shown
3. **Players play** → No time pressure

---

## Implementation Phases

### Phase 1: Database & Backend ✅
- Add fields to Match model
- Create migration
- Add model properties for time calculations
- Update admin interface

### Phase 2: Frontend Display ✅
- Add timer card to match detail page
- Add JavaScript countdown
- Add timer badges to match list

### Phase 3: Testing ✅
- Test with various time limits (5 min, 30 min, 60 min)
- Test timer expiration behavior
- Test matches without timers
- Test score submission after expiration

### Phase 4: Optional Enhancements
- Push notifications when timer expires
- Sound alert at 5 minutes, 1 minute
- Tournament-wide default timer setting
- Timer pause/resume functionality
- Timer statistics (average match duration vs time limit)

---

## Technical Considerations

### Timezone Handling
- All times stored in UTC using `timezone.now()`
- Display converted to user's timezone if needed
- Timer calculations use server time to avoid client clock drift

### Performance
- Timer calculations are properties (computed on-demand)
- No database writes during countdown (only on expiration)
- JavaScript countdown runs client-side (no server polling)

### Edge Cases
1. **Match waiting for court**: Timer doesn't start until `start_time` is set
2. **Match paused**: No pause functionality initially (future enhancement)
3. **Browser refresh**: Timer recalculates from `start_time` (no state lost)
4. **Multiple tabs**: Each tab runs independent countdown (all sync to same `start_time`)

---

## Migration Strategy

### For Existing Matches
- All existing matches: `time_limit_minutes = NULL` (no timer)
- Admin can retroactively add timers if needed
- No impact on completed matches

### For New Tournaments
- Admin can set default timer in tournament settings (future)
- Or set individually per match in admin panel

---

## Summary

This timer system provides:
- ✅ **Flexible**: Optional per-match configuration
- ✅ **Non-intrusive**: Reminder only, not a constraint
- ✅ **Visual**: Clear countdown with color-coded progress
- ✅ **Accurate**: Server-side time tracking, client-side display
- ✅ **Cosone-friendly**: Players can continue after expiration
- ✅ **Admin-controlled**: Easy configuration per match
- ✅ **Backwards compatible**: No impact on existing matches

The implementation follows Django best practices and integrates seamlessly with the existing match activation flow.
