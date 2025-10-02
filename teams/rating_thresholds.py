"""
Single source of truth for player rating category thresholds.
This module defines the rating boundaries used across the entire platform.
"""

# Rating category thresholds - SINGLE SOURCE OF TRUTH
RATING_THRESHOLDS = {
    'novice': {'min': 0, 'max': 110},
    'intermediate': {'min': 111, 'max': 150},  # Will be updated based on user confirmation
    'advanced': {'min': 151, 'max': 200},     # Will be updated based on user confirmation
    'pro': {'min': 201, 'max': float('inf')}
}

# Category display names and colors
CATEGORY_CONFIG = {
    'novice': {
        'display_name': 'Novice',
        'color': '#28a745',
        'bootstrap_class': 'secondary'
    },
    'intermediate': {
        'display_name': 'Intermediate', 
        'color': '#17a2b8',
        'bootstrap_class': 'info'
    },
    'advanced': {
        'display_name': 'Advanced',
        'color': '#fd7e14', 
        'bootstrap_class': 'primary'
    },
    'pro': {
        'display_name': 'Professional',
        'color': '#dc3545',
        'bootstrap_class': 'success'
    }
}

def get_player_category(rating_value):
    """
    Get the category for a given rating value.
    
    Args:
        rating_value (float): The player's rating value
        
    Returns:
        str: The category key ('novice', 'intermediate', 'advanced', 'pro')
    """
    for category, thresholds in RATING_THRESHOLDS.items():
        if thresholds['min'] <= rating_value <= thresholds['max']:
            return category
    
    # Fallback to pro if rating is extremely high
    return 'pro'

def get_category_display(category):
    """
    Get display information for a category.
    
    Args:
        category (str): The category key
        
    Returns:
        tuple: (display_name, bootstrap_class)
    """
    config = CATEGORY_CONFIG.get(category, CATEGORY_CONFIG['novice'])
    return (config['display_name'], config['bootstrap_class'])

def get_category_color(category):
    """
    Get the color for a category.
    
    Args:
        category (str): The category key
        
    Returns:
        str: Hex color code
    """
    return CATEGORY_CONFIG.get(category, CATEGORY_CONFIG['novice'])['color']

def get_all_categories():
    """
    Get all category information for chart generation.
    
    Returns:
        list: List of category dictionaries with thresholds, colors, and display info
    """
    categories = []
    for category, thresholds in RATING_THRESHOLDS.items():
        config = CATEGORY_CONFIG[category]
        categories.append({
            'key': category,
            'min': thresholds['min'],
            'max': thresholds['max'],
            'display_name': config['display_name'],
            'color': config['color'],
            'bootstrap_class': config['bootstrap_class']
        })
    return categories

