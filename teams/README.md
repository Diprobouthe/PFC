# PlayerProfile Extension for PFC Platform

## Overview

This extension adds a `PlayerProfile` model to the PFC Platform, providing additional player information and statistics without modifying the core `Player` model. This approach ensures system stability while allowing for enhanced player data tracking.

## Features

The `PlayerProfile` model adds the following capabilities:

- **Contact Information**: Email and phone number
- **Personal Information**: Date of birth and biography
- **Player Statistics**: Skill level, matches played, matches won, and win rate
- **Preferences**: Preferred playing position
- **Media**: Profile picture

## Implementation Details

### Model Structure

The `PlayerProfile` model is linked to the existing `Player` model through a one-to-one relationship:

```python
class PlayerProfile(models.Model):
    player = models.OneToOneField(
        Player, 
        on_delete=models.CASCADE,
        related_name='profile'
    )
    
    # Contact information
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    
    # Personal information
    date_of_birth = models.DateField(blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    
    # Player statistics
    skill_level = models.IntegerField(
        choices=[
            (1, 'Beginner'),
            (2, 'Intermediate'),
            (3, 'Advanced'),
            (4, 'Expert'),
            (5, 'Professional')
        ],
        default=1
    )
    matches_played = models.PositiveIntegerField(default=0)
    matches_won = models.PositiveIntegerField(default=0)
    
    # Preferences
    preferred_position = models.CharField(
        max_length=20,
        choices=[
            ('pointer', 'Pointer'),
            ('middle', 'Middle'),
            ('shooter', 'Shooter'),
            ('versatile', 'Versatile')
        ],
        blank=True,
        null=True
    )
    
    # Media
    profile_picture = models.ImageField(
        upload_to='player_profiles/',
        blank=True,
        null=True
    )
```

### Admin Integration

The admin interface has been updated to:
- Display PlayerProfile information in the Player admin view as an inline
- Provide a dedicated PlayerProfile admin view with filtering and search
- Show profile completion status in the Player list view

### Helper Methods

The `PlayerProfile` model includes these helper methods:

- `win_rate()`: Calculates the player's win percentage
- `update_match_stats(won=False)`: Updates match statistics after a game

## Installation Instructions

1. **Apply the Migration**:
   ```
   python manage.py migrate teams
   ```

2. **Create Profiles for Existing Players** (optional):
   You can create profiles for existing players using a management command or through the admin interface.

   Example script to create profiles for all players:
   ```python
   from teams.models import Player, PlayerProfile
   
   # Create profiles for players who don't have one
   for player in Player.objects.filter(profile__isnull=True):
       PlayerProfile.objects.create(player=player)
   ```

## Usage Examples

### Accessing Player Profile

```python
# Get a player's profile
player = Player.objects.get(id=1)
profile = player.profile  # Using the related_name

# Access profile information
email = profile.email
skill = profile.get_skill_level_display()
win_rate = profile.win_rate()
```

### Creating a Profile for a New Player

```python
# Create a player with profile
team = Team.objects.get(id=1)
player = Player.objects.create(name="John Doe", team=team)
profile = PlayerProfile.objects.create(
    player=player,
    email="john@example.com",
    skill_level=3,
    preferred_position="shooter"
)
```

### Updating Match Statistics

```python
# After a match, update player statistics
player = match.winner  # Assuming match has a winner field
if hasattr(player, 'profile'):
    player.profile.update_match_stats(won=True)
```

## Best Practices

1. **Check for Profile Existence**: Always check if a player has a profile before accessing it:
   ```python
   if hasattr(player, 'profile'):
       # Access profile
   ```

2. **Create Profiles Automatically**: Consider adding a signal to create profiles automatically when new players are created:
   ```python
   @receiver(post_save, sender=Player)
   def create_player_profile(sender, instance, created, **kwargs):
       if created:
           PlayerProfile.objects.create(player=instance)
   ```

3. **Keep Core Player Model Clean**: Continue using the Player model for essential information and the PlayerProfile for extended details.

## Future Enhancements

Potential future enhancements for the PlayerProfile model:

1. Add historical match data tracking
2. Implement player achievements/badges
3. Add social media links
4. Create player-to-player relationships (friends, rivals)
5. Integrate with user authentication system
