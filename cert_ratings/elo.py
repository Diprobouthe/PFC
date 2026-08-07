"""
cert_ratings.elo
================
Classic Elo calculation.

This module contains only the pure maths — no database access.
It can be replaced or extended with another algorithm without touching
the storage or processing logic in cert_ratings.processor.
"""


def expected_score(player_rating: float, opponent_rating: float, scale: int = 400) -> float:
    """
    Standard Elo expected score formula.

    E = 1 / (1 + 10 ^ ((opponent_rating - player_rating) / scale))
    """
    return 1.0 / (1.0 + 10.0 ** ((opponent_rating - player_rating) / scale))


def new_rating(
    current_rating: float,
    opponent_rating: float,
    won: bool,
    k_factor: int = 20,
    scale: int = 400,
) -> float:
    """
    Calculate the new Elo rating after one game.

    Args:
        current_rating: Player's current Elo rating.
        opponent_rating: Opponent's current Elo rating (or team average).
        won: True if the player/team won, False if they lost.
        k_factor: K-factor (default 20).
        scale: Rating scale divisor (default 400).

    Returns:
        New Elo rating as a float.

    Notes:
        - Score margin is ignored: a 13-0 win and a 13-12 win are both 1.0.
        - Draws are not supported by this spec; pass won=True for the winner.
    """
    actual = 1.0 if won else 0.0
    expected = expected_score(current_rating, opponent_rating, scale)
    return current_rating + k_factor * (actual - expected)


def calculate_team_elo_change(
    team_ratings: list[float],
    opponent_team_ratings: list[float],
    team_won: bool,
    k_factor: int = 20,
    scale: int = 400,
) -> tuple[float, float]:
    """
    Calculate the Elo change for every player on a team.

    For Doublettes and Triplettes:
      - Each team's strength is the average of its players' ratings.
      - Every player on the same team receives the same Elo change.

    Args:
        team_ratings: List of current Elo ratings for the team's players.
        opponent_team_ratings: List of current Elo ratings for the opposing team.
        team_won: True if this team won.
        k_factor: K-factor.
        scale: Rating scale.

    Returns:
        (per_player_change, new_per_player_rating_delta)
        where per_player_change is the same float applied to every player.
        The caller is responsible for applying the change to each player's
        individual current rating.
    """
    if not team_ratings:
        return 0.0
    if not opponent_team_ratings:
        opponent_avg = 1000.0  # fallback if opponent has no ratings
    else:
        opponent_avg = sum(opponent_team_ratings) / len(opponent_team_ratings)

    team_avg = sum(team_ratings) / len(team_ratings)

    # The change is calculated once using team averages.
    # Every player on the team gets the same change.
    actual = 1.0 if team_won else 0.0
    expected = expected_score(team_avg, opponent_avg, scale)
    change = k_factor * (actual - expected)
    return change
