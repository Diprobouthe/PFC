# Timer Inheritance Issue - Root Cause Found

## Problem
Scenario has `default_time_limit_minutes = 15`, but matches created from this scenario have "No timer"

## Investigation Results

### Scenario Configuration
- URL: https://8000-i3h5t5fooex7a987mj80g-e785601b.manusvm.computer/admin/simple_creator/tournamentscenario/4/change/
- Scenario: "adv"
- **Default time limit minutes: 15** ✅ (configured correctly)

### Tournament Configuration
- URL: https://8000-i3h5t5fooex7a987mj80g-e785601b.manusvm.computer/admin/tournaments/tournament/23/change/
- Tournament: "adv Doubles - 2025-12-04"
- **Default time limit minutes: EMPTY** ❌ (field at index 62 is empty!)

### Match Configuration
- URL: https://8000-i3h5t5fooex7a987mj80g-e785601b.manusvm.computer/admin/matches/match/
- Matches #6 and #7
- **Timer: "No timer"** ❌ (no time limit set)

## Root Cause

The tournament's `default_time_limit_minutes` field is **EMPTY**, even though:
1. The scenario has it set to 15
2. The code at line 201 in `simple_creator/views.py` should copy it:
   ```python
   default_time_limit_minutes=scenario.default_time_limit_minutes
   ```

## Possible Explanations

1. **Tournament created BEFORE scenario timer was added**
   - The "adv" scenario timer was configured AFTER this tournament was created
   - Solution: Recreate tournament OR manually set timer in tournament admin

2. **Scenario timer was NULL when tournament was created**
   - The scenario's `default_time_limit_minutes` was NULL/None at creation time
   - Solution: Ensure scenario timer is set before creating tournaments

3. **Migration timing issue**
   - The migration adding `default_time_limit_minutes` to scenarios wasn't applied yet
   - Solution: Ensure migrations are applied before creating tournaments

## Verification

The code is correct:
- ✅ Line 201 in `simple_creator/views.py` copies timer from scenario
- ✅ All 12 match creation locations use `tournament.default_time_limit_minutes`
- ✅ Admin interface shows timer fields correctly

## Solution

**For existing tournaments:**
Manually set `default_time_limit_minutes` in tournament admin, then regenerate matches

**For new tournaments:**
Ensure scenario has timer configured BEFORE creating tournament - the code will work correctly!
