# Public Player Statistics Pages Documentation

## Overview

This implementation adds public-facing player statistics pages to the PFC Platform, including:

1. **Player Leaderboard**: A comprehensive leaderboard showing all players with their statistics, including filtering and sorting options
2. **Individual Player Profiles**: Detailed profile pages for each player showing personal information, statistics, and match history

## Features

### Player Leaderboard
- Displays all players with profiles in a sortable, filterable table
- Shows key statistics: matches played, matches won, win rate
- Includes filtering by team, skill level, and preferred position
- Allows sorting by different statistics (win rate, matches played, etc.)
- Visual indicators for skill levels and win rates
- Links to individual player profiles

### Player Profile Pages
- Displays personal information (name, email, phone, etc.)
- Shows player statistics with visual indicators
- Includes match history with results and scores
- Links back to the leaderboard and match details
- Responsive design for both desktop and mobile

## Implementation Details

### Files Added/Modified

1. **Templates**:
   - `teams/templates/teams/player_leaderboard.html`: Leaderboard page template
   - `teams/templates/teams/player_profile.html`: Individual player profile template

2. **Views**:
   - Added `player_leaderboard()` and `player_profile()` functions to `teams/views.py`

3. **URLs**:
   - Added URL patterns in `teams/urls.py`:
     - `/teams/players/leaderboard/` for the leaderboard
     - `/teams/player/<player_id>/profile/` for individual profiles

### Integration with Existing Code

- Uses the existing `Player` and new `PlayerProfile` models
- Integrates with the `Match` model to show match history
- Follows the site's existing URL structure and navigation patterns
- Compatible with the existing authentication system

## Installation Instructions

1. **Update Files**:
   - Replace or update `teams/views.py` with the new version
   - Replace or update `teams/urls.py` with the new version
   - Add the new template files to `teams/templates/teams/`

2. **Add Navigation Links**:
   - Add a link to the player leaderboard in your main navigation:
   ```html
   <a href="{% url 'player_leaderboard' %}">Player Leaderboard</a>
   ```
   - Add links to player profiles from team detail pages:
   ```html
   <a href="{% url 'player_profile' player.id %}">View Profile</a>
   ```

3. **Apply Migrations**:
   - No additional migrations are needed if the PlayerProfile model is already implemented

## Usage Examples

### Accessing the Player Leaderboard

```python
# In a view or template
from django.urls import reverse

# Generate URL to player leaderboard
leaderboard_url = reverse('player_leaderboard')

# Generate URL with filters
from django.urls import reverse
from urllib.parse import urlencode

base_url = reverse('player_leaderboard')
query_params = urlencode({
    'team': 1,
    'skill_level': 3,
    'sort_by': 'matches_won',
    'order': 'desc'
})
filtered_url = f"{base_url}?{query_params}"
```

### Accessing Individual Player Profiles

```python
# In a view or template
from django.urls import reverse

# Generate URL to a player's profile
player_profile_url = reverse('player_profile', kwargs={'player_id': player.id})
```

### Updating Player Statistics

When a match is completed, update player statistics:

```python
def update_player_stats(match):
    # Update statistics for winning team players
    for player in match.winner.players.all():
        if hasattr(player, 'profile'):
            player.profile.update_match_stats(won=True)
    
    # Update statistics for losing team players
    losing_team = match.team2 if match.winner == match.team1 else match.team1
    for player in losing_team.players.all():
        if hasattr(player, 'profile'):
            player.profile.update_match_stats(won=False)
```

## Customization Options

### Styling

The templates use Bootstrap classes for styling. You can customize the appearance by:
- Modifying the CSS classes in the templates
- Adding custom CSS to your site's stylesheet
- Adjusting the card layouts and colors

### Additional Statistics

To add more player statistics:
1. Add fields to the `PlayerProfile` model
2. Update the templates to display the new statistics
3. Modify the `update_match_stats` method to track the new statistics

### Extending Functionality

Potential extensions:
- Add player achievements/badges
- Implement tournament-specific statistics
- Add player comparison features
- Create team statistics aggregated from player data

## Best Practices

1. **Performance Optimization**:
   - Use `select_related` and `prefetch_related` for database queries
   - Consider pagination for the leaderboard with many players
   - Cache frequently accessed leaderboard data

2. **User Experience**:
   - Ensure responsive design works on all device sizes
   - Provide clear navigation between related pages
   - Use visual indicators (progress bars, badges) for better data comprehension

3. **Data Integrity**:
   - Always check if a player has a profile before accessing it
   - Update statistics consistently when matches are completed
   - Consider adding data validation for statistics updates
