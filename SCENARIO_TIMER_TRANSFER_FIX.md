# Scenario Timer Transfer Fix

## 🐛 The Problem

**Scenario has timer** → **Tournament created from scenario has NO timer** → **Matches have NO timer**

### Example
- Scenario #5 (advt3): `default_time_limit_minutes = 15` ✅
- Tournament #26 created from scenario #5: `default_time_limit_minutes = None` ❌
- Matches in tournament #26: No timer ❌

---

## 🔍 Root Cause Analysis

### The Investigation Journey

1. **First suspicion**: Match generation code missing timer  
   ❌ **Wrong** - All 12 match creation locations already had `time_limit_minutes=self.tournament.default_time_limit_minutes`

2. **Second suspicion**: Tournament creation in `simple_creator/views.py` missing timer  
   ❌ **Wrong** - That file had the timer code, but wasn't being used!

3. **Third suspicion**: Wrong file being executed  
   ✅ **CORRECT** - The system was using `pfc_core/simple_creator.py`, NOT `simple_creator/views.py`!

### The Real Issue

**File being executed:** `/home/ubuntu/pfc_platform/pfc_core/simple_creator.py`  
**File we edited:** `/home/ubuntu/pfc_platform/simple_creator/views.py`

The main URL routing (`pfc_core/urls.py`) imports from `pfc_core.simple_creator`, not from the `simple_creator` app!

```python
# pfc_core/urls.py
from pfc_core import simple_creator  # ← This is the file being used!

urlpatterns = [
    path('simple/', simple_creator.simple_creator_home, name='simple_creator_home'),
    path('simple/create/', simple_creator.create_simple_tournament, name='create_simple_tournament'),
]
```

---

## ✅ The Solution

### Code Changes in `/home/ubuntu/pfc_platform/pfc_core/simple_creator.py`

#### 1. Get TournamentScenario Object (Lines 165-172)

```python
# Get timer from scenario object if available
timer_minutes = None
if USE_DYNAMIC_SCENARIOS and 'id' in scenario:
    try:
        scenario_obj = TournamentScenario.objects.get(id=scenario['id'])
        timer_minutes = scenario_obj.default_time_limit_minutes
    except TournamentScenario.DoesNotExist:
        pass
```

**Why this is needed:**
- The `scenario` variable is a dictionary from `get_available_scenarios()`
- It doesn't include `default_time_limit_minutes` in the dict
- We need to fetch the actual TournamentScenario object to get the timer

#### 2. Apply Timer to Tournament Creation (Line 189)

```python
tournament = Tournament.objects.create(
    name=tournament_name,
    description=f"Simple {scenario['name']} tournament with {num_courts} courts",
    start_datetime=start_datetime,
    end_datetime=end_datetime,
    registration_deadline=start_datetime - timedelta(hours=1),
    tournament_type=scenario['tournament_type'],
    draft_type=scenario['draft_type'],
    num_rounds=scenario.get('num_rounds'),
    matches_per_team=scenario.get('matches_per_team'),
    is_active=True,
    is_melee=True,
    melee_format="triplets" if format_type == "triples" else "doublets",
    melee_teams_generated=False,
    automation_status="idle",
    max_participants=max_players,
    default_time_limit_minutes=timer_minutes  # ← Apply scenario timer
)
```

---

## 🧪 Testing Results

### Before Fix
```python
# Scenario #5
default_time_limit_minutes = 15

# Tournament #26 (created from scenario #5)
default_time_limit_minutes = None  # ❌
```

### After Fix
```python
# Scenario #5
default_time_limit_minutes = 15

# Tournament #30 (created from scenario #5 after fix)
default_time_limit_minutes = 15  # ✅ WORKS!
```

### Test Command
```bash
python manage.py shell -c "from tournaments.models import Tournament; t = Tournament.objects.latest('id'); print(f'Tournament #{t.id}: {t.name}'); print(f'Timer: {t.default_time_limit_minutes} minutes')"
```

### Test Output
```
Tournament #30: advt3 Doubles - 2025-12-04
Timer: 15 minutes  ✅
```

---

## 📊 Complete Flow

### Scenario → Tournament → Matches

```
┌─────────────────────────────────┐
│  TournamentScenario #5          │
│  default_time_limit_minutes: 15 │
└────────────┬────────────────────┘
             │
             │ ✅ Transfer via pfc_core/simple_creator.py
             │
             ▼
┌─────────────────────────────────┐
│  Tournament #30                 │
│  default_time_limit_minutes: 15 │
└────────────┬────────────────────┘
             │
             │ ✅ Auto-apply via tournaments/models.py
             │
             ▼
┌─────────────────────────────────┐
│  Match #1, #2, #3...            │
│  time_limit_minutes: 15         │
└─────────────────────────────────┘
```

---

## 🎯 Impact

### What This Fixes

1. ✅ **Scenario timer → Tournament timer** transfer works
2. ✅ **Tournament timer → Match timer** auto-apply works (already worked)
3. ✅ **Matches created with correct timer** from scenario configuration

### What This Enables

- **Admins** can set default timer in scenario once
- **All tournaments** created from that scenario inherit the timer
- **All matches** in those tournaments automatically get the timer
- **Zero manual configuration** needed per tournament or match

---

## 📝 Files Modified

1. `/home/ubuntu/pfc_platform/pfc_core/simple_creator.py`
   - Lines 165-172: Get timer from TournamentScenario object
   - Line 189: Apply timer to Tournament creation

---

## ✅ Deployment Checklist

- [x] Code changes applied
- [x] Tested with scenario #5 (advt3)
- [x] Tournament #30 created successfully
- [x] Timer transferred correctly (15 minutes)
- [x] No migration required (uses existing fields)
- [x] Backwards compatible (timer is optional)

---

## 🚀 Ready for Production

**Status:** ✅ **WORKING**  
**Migration Required:** ❌ No  
**Backwards Compatible:** ✅ Yes  
**Tested:** ✅ Yes

The timer transfer from scenario to tournament is now fully functional!
