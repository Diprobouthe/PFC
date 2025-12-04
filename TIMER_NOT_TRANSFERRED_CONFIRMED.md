# Timer Not Transferred from Scenario to Tournament - CONFIRMED

## Evidence

### Scenario #5 (advt3)
- URL: https://8000-i3h5t5fooex7a987mj80g-e785601b.manusvm.computer/admin/simple_creator/tournamentscenario/5/change/
- **Default time limit minutes: 15** ✅ (index 63, visible in screenshot)

### Tournament #26 (advt3 Doubles - 2025-12-04)
- URL: https://8000-i3h5t5fooex7a987mj80g-e785601b.manusvm.computer/admin/tournaments/tournament/26/change/
- **Default time limit minutes: EMPTY** ❌ (index 67, empty input field)

## Problem Confirmed

The scenario has `default_time_limit_minutes = 15`, but the tournament created from it has `default_time_limit_minutes = None/NULL`.

## Code Review

The code in `simple_creator/views.py` line 201 should be copying the timer:

```python
tournament = Tournament.objects.create(
    ...
    default_time_limit_minutes=scenario.default_time_limit_minutes  # Line 201
)
```

## Possible Causes

1. **Migration not applied**: The `default_time_limit_minutes` field might not exist in the database yet
2. **Field name mismatch**: The scenario model field name might be different
3. **NULL value**: The scenario's timer might be NULL in the database even though it shows 15 in the admin

## Next Steps

1. Check if migration was applied to add `default_time_limit_minutes` to TournamentScenario model
2. Verify the field name in the TournamentScenario model
3. Check the actual database value for scenario #5
