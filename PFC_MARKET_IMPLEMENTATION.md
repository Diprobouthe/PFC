# PFC MARKET - Stock Exchange Style Player Leaderboard

## Overview

The **PFC MARKET** is a revolutionary stock exchange-style leaderboard that displays all players ranked by their rating with real-time trend indicators. This feature transforms player rankings into an engaging, dynamic market board similar to financial stock exchanges.

## Features Implemented

### 1. Homepage Reorganization

**Friendly Games Section - 2x2 Button Grid:**

The Friendly Games section has been reorganized from a 3-button row into a professional 2x2 grid layout:

| Row 1 | Row 1 |
|-------|-------|
| **Create Game** (Green) | **Join Game** (White outline) |
| **Submit Score** (Yellow) | **Friendly Game Statistics** (Cyan) |

**PFC MARKET Card:**

Replaced the standalone "Friendly Game Statistics" card with a new **PFC MARKET** card featuring:
- Dark gradient background (stock market theme)
- Cyan/blue color scheme (#00d4ff)
- Professional stock exchange styling
- Chart icon
- Direct link to the market leaderboard

### 2. PFC MARKET Leaderboard Page

**URL:** `/teams/players/pfc-market/`

**Visual Design:**
- **Stock exchange theme** with dark gradient background
- **Cyan accents** (#00d4ff) for professional financial market look
- **Responsive layout** that works on all devices
- **Animated trend arrows** with pulsing effects

**Market Statistics Dashboard:**

Displays key market metrics at the top:
- **Total Players** - Total number of ranked players
- **Gainers** - Players with positive trends (green)
- **Losers** - Players with negative trends (red)
- **Average Rating** - Mean rating across all players
- **Top Gainer** - Player with highest positive change

**Player Rankings Table:**

| Column | Description |
|--------|-------------|
| **Rank** | Player's position (1st, 2nd, 3rd...) |
| **Player** | Player name and team |
| **Team** | Team affiliation |
| **Rating** | Current rating value (monospace font) |
| **Trend** | Arrow indicator (↑ ↓ →) |
| **Change** | Rating change from last 2 games |

**Rank Badges:**
- **Top 3:** Gold gradient with glow effect
- **Top 10:** Silver gradient
- **Others:** Transparent with subtle color

### 3. Trend Indicators

**Trend Calculation Logic:**

The system analyzes each player's **last 2 games** from their rating history to determine trend:

```python
# Get last 2 games
recent_games = history[-2:] if len(history) >= 2 else history[-1:]

# Calculate total change
total_change = sum(game.get('change', 0) for game in recent_games)

# Determine direction
if total_change > 0: direction = 'up'      # ↑ Green
elif total_change < 0: direction = 'down'  # ↓ Red
else: direction = 'neutral'                # → Gray
```

**Visual Indicators:**
- **↑ Green Arrow** - Player is gaining points (winning trend)
- **↓ Red Arrow** - Player is losing points (losing trend)
- **→ Gray Arrow** - No change or no recent games

**Animated Effects:**
- Green arrows pulse with a glowing effect
- Red arrows pulse with a warning effect
- Smooth transitions and hover states

### 4. Dual Sorting System

**Two Sorting Options:**

1. **By Rating** (Default)
   - Players ranked by highest rating first
   - Shows who has the best overall performance
   - URL: `/teams/players/pfc-market/` or `?sort=rating`

2. **By Trend**
   - Players ranked by biggest gainers first
   - Shows who is improving the fastest
   - Biggest losers appear at the bottom
   - URL: `/teams/players/pfc-market/?sort=trend`

**Sorting Controls:**
- Two prominent buttons: "🏆 By Rating" and "📊 By Trend"
- Active button highlighted with cyan background
- Instant sorting without page reload feel

## Technical Implementation

### Data Model

**Uses PlayerProfile Model:**
- Rating stored in `PlayerProfile.value` (FloatField, default 100.0)
- Rating history in `PlayerProfile.rating_history` (JSONField)
- Each history entry contains:
  - `timestamp` - When the change occurred
  - `old_value` - Rating before the game
  - `new_value` - Rating after the game
  - `change` - Rating change (+/-)
  - `opponent_value` - Opponent's rating
  - `own_score` - Player's score
  - `opponent_score` - Opponent's score
  - `match_type` - 'tournament' or 'friendly'
  - `match_id` - Match identifier

### View Logic

**File:** `teams/views_market.py`

**Key Functions:**

1. **`calculate_player_trend(profile)`**
   - Analyzes last 2 games from rating history
   - Returns trend direction, change amount, and percentage
   - Handles edge cases (no games, 1 game only)

2. **`pfc_market(request)`**
   - Fetches all PlayerProfile objects with related team data
   - Calculates trend for each player
   - Applies sorting based on query parameter
   - Assigns ranks after sorting
   - Calculates market statistics
   - Renders the stock exchange template

### Template

**File:** `teams/templates/teams/pfc_market.html`

**CSS Features:**
- Custom stock market color scheme
- Gradient backgrounds
- Animated trend arrows
- Responsive table layout
- Professional typography with letter spacing
- Hover effects on table rows

**JavaScript:**
- No custom JavaScript required
- Pure CSS animations
- Server-side sorting via URL parameters

## User Experience Flow

### From Homepage

1. User sees **PFC MARKET** card on homepage (dark theme, cyan colors)
2. Clicks the card or button
3. Navigates to `/teams/players/pfc-market/`

### On Market Page

1. **View Market Statistics** - See overall market health
2. **Browse Rankings** - Scroll through player list
3. **Check Trends** - See who's rising or falling
4. **Sort by Trend** - Click "By Trend" to see biggest movers
5. **Sort by Rating** - Click "By Rating" to see top players
6. **Return Home** - Click "Back to Home" button

## Example Data

**Market Statistics:**
- Total Players: 5
- Gainers: ↑ 2
- Losers: ↓ 2
- Average Rating: 100.0
- Top Gainer: P2 (+3.2)

**Player Rankings (By Rating):**

| Rank | Player | Team | Rating | Trend | Change |
|------|--------|------|--------|-------|---------|
| 1 | P2 | Friendly Games | 103.2 | ↑ | +3.2 (2 games) |
| 2 | P3 | Mêlée Team 1 | 102.0 | ↑ | +2.0 (1 game) |
| 3 | p5 | Friendly Games | 100.0 | → | 0.0 (0 games) |
| 4 | P4 | Mêlée Team 2 | 98.0 | ↓ | -2.0 (1 game) |
| 5 | P1 | Friendly Games | 96.8 | ↓ | -3.2 (2 games) |

**Player Rankings (By Trend):**

| Rank | Player | Change | Rating |
|------|--------|---------|---------|
| 1 | P2 | +3.2 ↑ | 103.2 |
| 2 | P3 | +2.0 ↑ | 102.0 |
| 3 | p5 | 0.0 → | 100.0 |
| 4 | P4 | -2.0 ↓ | 98.0 |
| 5 | P1 | -3.2 ↓ | 96.8 |

## Benefits

### For Players

1. **Motivation** - See progress visually with trend indicators
2. **Competition** - Compare ratings with other players
3. **Engagement** - Stock market theme makes rankings exciting
4. **Transparency** - Clear understanding of rating changes
5. **Real-time** - Always up-to-date with latest games

### For Organizers

1. **Player Engagement** - Keeps players interested in the platform
2. **Competitive Spirit** - Encourages more participation
3. **Data Visualization** - Easy to see player performance trends
4. **Professional Look** - Stock exchange theme adds prestige
5. **No Manual Updates** - Automatically updates with each game

## Files Modified/Created

### New Files
1. `/teams/views_market.py` - Market leaderboard view logic
2. `/teams/templates/teams/pfc_market.html` - Stock exchange UI template

### Modified Files
1. `/teams/views.py` - Import pfc_market view
2. `/teams/urls.py` - Add pfc_market URL pattern
3. `/templates/home.html` - Reorganize layout, add PFC MARKET card

## Installation & Deployment

**No Database Changes Required:**
- Uses existing PlayerProfile model
- Uses existing rating_history field
- No migrations needed

**Deployment Steps:**
1. Extract the deployment package
2. Restart Django server
3. Feature is immediately available

**Testing:**
1. Navigate to homepage
2. Click PFC MARKET card
3. Verify player rankings display
4. Test sorting by clicking "By Trend"
5. Verify trend indicators show correctly

## Future Enhancements

**Potential Additions:**
1. **Historical Charts** - Show rating progression over time
2. **Filters** - Filter by team, skill level, or date range
3. **Search** - Search for specific players
4. **Export** - Download rankings as PDF or CSV
5. **Notifications** - Alert players when they enter top 10
6. **Achievements** - Badges for top gainers, longest winning streaks
7. **Predictions** - AI-powered rating predictions

## Troubleshooting

**Issue: No players showing**
- Solution: Ensure PlayerProfile objects exist with rating_history data

**Issue: Trend arrows not showing**
- Solution: Check that players have at least 1 game in rating_history

**Issue: Sorting not working**
- Solution: Verify URL parameter is being passed correctly

**Issue: Styling looks different**
- Solution: Clear browser cache and reload CSS

## Summary

The **PFC MARKET** feature successfully transforms the player leaderboard into an engaging, stock exchange-style ranking system. With real-time trend indicators, dual sorting options, and a professional visual design, it provides players with an exciting way to track their progress and compete with others.

**Status:** ✅ **COMPLETE, TESTED, AND PRODUCTION READY**

**Key Achievements:**
- ✅ Stock exchange visual theme
- ✅ Trend indicators based on last 2 games
- ✅ Dual sorting (by rating and by trend)
- ✅ Market statistics dashboard
- ✅ Responsive design
- ✅ Animated effects
- ✅ Homepage integration
- ✅ Zero database changes required
