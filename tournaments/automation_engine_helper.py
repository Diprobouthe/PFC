# Helper method to add to automation_engine.py

def _get_next_overall_round_number(self):
    """Get the next overall round number for the tournament"""
    current_round = self.tournament.current_round_number or 0
    return current_round + 1
