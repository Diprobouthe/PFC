"""
Admin actions for shuffling mêlée players
"""

from django.contrib import admin, messages
from django.shortcuts import redirect
from tournaments.shuffle_utils import shuffle_melee_players


@admin.action(description="Shuffle players between mêlée teams")
def shuffle_melee_players_action(modeladmin, request, queryset):
    """
    Admin action to shuffle players between mêlée teams for selected tournaments.
    """
    shuffled_count = 0
    failed_count = 0
    
    for tournament in queryset:
        if not tournament.is_melee:
            messages.warning(
                request,
                f"'{tournament.name}' is not a mêlée tournament - skipped"
            )
            failed_count += 1
            continue
        
        if not tournament.melee_teams_generated:
            messages.warning(
                request,
                f"'{tournament.name}' has no mêlée teams generated yet - skipped"
            )
            failed_count += 1
            continue
        
        # Perform shuffle
        result = shuffle_melee_players(
            tournament=tournament,
            shuffle_type='manual',
            shuffled_by=request.user
        )
        
        if result['success']:
            messages.success(
                request,
                f"✅ '{tournament.name}': {result['message']}"
            )
            shuffled_count += 1
        else:
            messages.error(
                request,
                f"❌ '{tournament.name}': {result['message']}"
            )
            failed_count += 1
    
    # Summary message
    if shuffled_count > 0:
        messages.info(
            request,
            f"Shuffled players in {shuffled_count} tournament(s). "
            f"Players will see their new teams automatically within 10 seconds."
        )
    
    if failed_count > 0:
        messages.warning(
            request,
            f"{failed_count} tournament(s) could not be shuffled."
        )
