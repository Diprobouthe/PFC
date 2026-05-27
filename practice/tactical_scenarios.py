"""
Tactical Scenarios Data Structure

This file defines the 5 tactical scenarios that will be used in the Tactical Drill mode.
It follows the exact same structure as the TdP ateliers to allow reusing the UI and logic.
"""

TACTICAL_ATELIERS = [
    {
        'number': 1,
        'name': 'Scenario 1',
        'label': 'Recover the Point (Open)',
        'description': 'You play for the black team. The white team holds the point near the jack. Recover the point by shooting the white boule.',
        'icon': '🎯',
        'has_jack_target': False,
        'legend': [
            {'color': '#424242', 'label': 'Your Team (Black)'},
            {'color': '#e0e0e0', 'label': 'Opponent (White)'},
            {'color': '#e53935', 'label': 'Jack'}
        ],
        'svg': '''<svg width="80" height="64" viewBox="0 0 80 64" fill="none" xmlns="http://www.w3.org/2000/svg">
            <ellipse cx="40" cy="52" rx="22" ry="5" fill="none" stroke="#d1d5db" stroke-width="1.5" stroke-dasharray="4,3"/>
            <circle cx="40" cy="25" r="6" fill="#e53935" stroke="#b71c1c" stroke-width="1.5"/>
            <circle cx="38" cy="23" r="1.8" fill="rgba(255,255,255,0.4)"/>
            <circle cx="40" cy="38" r="13" fill="#e0e0e0" stroke="#9e9e9e" stroke-width="2"/>
            <circle cx="36" cy="33" r="3.5" fill="rgba(255,255,255,0.6)"/>
            <line x1="40" y1="8" x2="40" y2="22" stroke="#1a56db" stroke-width="2" marker-end="url(#a1)"/>
            <defs><marker id="a1" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="#1a56db"/></marker></defs>
        </svg>''',
        'pts': [0, 1, 3, 5],
    },
    {
        'number': 2,
        'name': 'Scenario 2',
        'label': 'Shoot the Blocker',
        'description': 'You play for the black team. A white boule is blocking the direct path to the jack. Clear the lane.',
        'icon': '⚫🎯',
        'has_jack_target': False,
        'legend': [
            {'color': '#424242', 'label': 'Your Team (Black)'},
            {'color': '#e0e0e0', 'label': 'Opponent (White)'},
            {'color': '#e53935', 'label': 'Jack'}
        ],
        'svg': '''<svg width="80" height="64" viewBox="0 0 80 64" fill="none" xmlns="http://www.w3.org/2000/svg">
            <ellipse cx="40" cy="54" rx="22" ry="5" fill="none" stroke="#d1d5db" stroke-width="1.5" stroke-dasharray="4,3"/>
            <circle cx="40" cy="18" r="6" fill="#e53935" stroke="#b71c1c" stroke-width="1.5"/>
            <circle cx="38" cy="16" r="1.8" fill="rgba(255,255,255,0.4)"/>
            <circle cx="40" cy="40" r="13" fill="#e0e0e0" stroke="#9e9e9e" stroke-width="2"/>
            <circle cx="36" cy="35" r="3.5" fill="rgba(255,255,255,0.6)"/>
            <line x1="40" y1="5" x2="40" y2="24" stroke="#1a56db" stroke-width="2" marker-end="url(#a2)"/>
            <defs><marker id="a2" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="#1a56db"/></marker></defs>
        </svg>''',
        'pts': [0, 1, 3, 5],
    },
    {
        'number': 3,
        'name': 'Scenario 3',
        'label': 'Protect the Jack',
        'description': 'You play for the black team. The opponent has a boule threatening to take the point. Shoot it cleanly without moving the jack.',
        'icon': '🛡️',
        'has_jack_target': False,
        'legend': [
            {'color': '#424242', 'label': 'Your Team (Black)'},
            {'color': '#e0e0e0', 'label': 'Opponent (White)'},
            {'color': '#e53935', 'label': 'Jack'}
        ],
        'svg': '''<svg width="80" height="64" viewBox="0 0 80 64" fill="none" xmlns="http://www.w3.org/2000/svg">
            <ellipse cx="40" cy="52" rx="28" ry="5" fill="none" stroke="#d1d5db" stroke-width="1.5" stroke-dasharray="4,3"/>
            <circle cx="28" cy="38" r="6" fill="#e53935" stroke="#b71c1c" stroke-width="1.5"/>
            <circle cx="26" cy="36" r="1.8" fill="rgba(255,255,255,0.4)"/>
            <circle cx="52" cy="38" r="13" fill="#e0e0e0" stroke="#9e9e9e" stroke-width="2"/>
            <circle cx="48" cy="33" r="3.5" fill="rgba(255,255,255,0.6)"/>
            <line x1="52" y1="6" x2="52" y2="22" stroke="#1a56db" stroke-width="2" marker-end="url(#a3)"/>
            <defs><marker id="a3" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="#1a56db"/></marker></defs>
        </svg>''',
        'pts': [0, 1, 3, 5],
    },
    {
        'number': 4,
        'name': 'Scenario 4',
        'label': 'Surgical Strike',
        'description': 'You play for the black team. The white boule holds the point, but your black boule is right behind it. Shoot the white without hitting yours.',
        'icon': '🔪',
        'has_jack_target': False,
        'legend': [
            {'color': '#424242', 'label': 'Your Team (Black)'},
            {'color': '#e0e0e0', 'label': 'Opponent (White)'},
            {'color': '#e53935', 'label': 'Jack'}
        ],
        'svg': '''<svg width="80" height="64" viewBox="0 0 80 64" fill="none" xmlns="http://www.w3.org/2000/svg">
            <ellipse cx="40" cy="55" rx="22" ry="5" fill="none" stroke="#d1d5db" stroke-width="1.5" stroke-dasharray="4,3"/>
            <circle cx="40" cy="26" r="13" fill="#424242" stroke="#212121" stroke-width="2"/>
            <circle cx="37" cy="22" r="3" fill="rgba(255,255,255,0.2)"/>
            <circle cx="40" cy="42" r="13" fill="#e0e0e0" stroke="#9e9e9e" stroke-width="2"/>
            <circle cx="37" cy="38" r="3" fill="rgba(255,255,255,0.6)"/>
            <line x1="40" y1="5" x2="40" y2="11" stroke="#1a56db" stroke-width="2" marker-end="url(#a4)"/>
            <defs><marker id="a4" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="#1a56db"/></marker></defs>
        </svg>''',
        'pts': [0, 1, 3, 5],
    },
    {
        'number': 5,
        'name': 'Scenario 5',
        'label': 'Kill the End (Shoot Jack)',
        'description': 'You play for the black team. The opponent has 4 points on the ground and you have no boules left. Shoot the jack to kill the end.',
        'icon': '🔴',
        'has_jack_target': True,
        'legend': [
            {'color': '#424242', 'label': 'Your Team (Black)'},
            {'color': '#e0e0e0', 'label': 'Opponent (White)'},
            {'color': '#e53935', 'label': 'Jack'}
        ],
        'svg': '''<svg width="80" height="64" viewBox="0 0 80 64" fill="none" xmlns="http://www.w3.org/2000/svg">
            <ellipse cx="40" cy="52" rx="28" ry="5" fill="none" stroke="#d1d5db" stroke-width="1.5" stroke-dasharray="4,3"/>
            <circle cx="40" cy="36" r="16" fill="none" stroke="#fca5a5" stroke-width="1.5" stroke-dasharray="3,3"/>
            <circle cx="40" cy="36" r="8" fill="#e53935" stroke="#b71c1c" stroke-width="2"/>
            <circle cx="37.5" cy="33" r="2.5" fill="rgba(255,255,255,0.4)"/>
            
            <circle cx="20" cy="20" r="13" fill="#e0e0e0" stroke="#9e9e9e" stroke-width="2"/>
            <circle cx="60" cy="20" r="13" fill="#e0e0e0" stroke="#9e9e9e" stroke-width="2"/>
            <circle cx="20" cy="50" r="13" fill="#e0e0e0" stroke="#9e9e9e" stroke-width="2"/>
            <circle cx="60" cy="50" r="13" fill="#e0e0e0" stroke="#9e9e9e" stroke-width="2"/>
            
            <line x1="40" y1="6" x2="40" y2="25" stroke="#1a56db" stroke-width="2" marker-end="url(#a5)"/>
            <defs><marker id="a5" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="#1a56db"/></marker></defs>
        </svg>''',
        'pts': [0, 3, 5, 5],
    },
]
