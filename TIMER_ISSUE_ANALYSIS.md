# Timer Issue Analysis

## Problem

**Scenario:** "adv" (ID: 4)
- Has `default_time_limit_minutes = 15` configured

**Matches from this scenario:**
- Match #7: "adv Doubles - 2025-12-04" - Shows "No timer" ❌
- Match #6: "adv Doubles - 2025-12-04" - Shows "No timer" ❌

**Expected:** Matches should have 15-minute timer
**Actual:** Matches have "No timer"

## Root Cause

The tournament was created from the scenario with `default_time_limit_minutes = 15`, but when the **matches are generated**, they are not inheriting the timer from the tournament.

## Code Flow

1. ✅ Scenario has `default_time_limit_minutes = 15`
2. ✅ Tournament is created with `default_time_limit_minutes = 15` (from scenario)
3. ❌ Matches are generated WITHOUT `time_limit_minutes` field

## Where Matches Are Generated

Matches are generated in `tournaments/models.py` in various methods:
- `generate_round_robin_matches()`
- `generate_knockout_matches()`
- `generate_swiss_matches()`
- `generate_smart_swiss_matches()`
- `generate_wtf_matches()`
- Stage-based match generation

**Issue:** None of these methods check `tournament.default_time_limit_minutes` when creating matches.

## Solution

Update all match creation locations to include:
```python
time_limit_minutes=self.default_time_limit_minutes
```

This is the same fix we did earlier, but we need to ensure it's applied to ALL match creation locations, not just the ones in Tournament model.
