"""
Helper function to find which court complex a court belongs to
"""
from courts.models import CourtComplex

def get_court_complex_for_court(court):
    """
    Find which court complex contains the given court
    Returns the complex or None if not assigned
    """
    try:
        return CourtComplex.objects.filter(courts=court).first()
    except:
        return None

