"""
Hidden Target — Scenario Pack 1
================================
5 ateliers × 4 shots = 20 shots, max 100 pts.

Each atelier presents a boule cluster where the target boule (orange)
is partially or fully hidden behind obstacle boules (grey).
The player must identify the target and shoot through/around the obstacles.

Visual language (mirrors the reference images):
  - Orange boule  = target (the one to hit)
  - Grey boules   = obstacles / cluster members
  - Blue arrow    = shot direction
  - Dashed ellipse = ground circle / landing zone

Scoring (same as TdP engine):
  ★  Carreau       = 5 pts  (direct hit, target moves cleanly)
  ☆  Petit Carreau = 3 pts  (grazing hit, partial displacement)
  ✓  Hit           = 1 pt   (contact, minimal movement)
  ✕  Miss          = 0 pts
"""

HIDDEN_TARGET_ATELIERS = [
    {
        "number": 1,
        "label": "Single Hidden — Direct Overhead",
        "short": "1 Hide",
        "icon": "🎯",
        "description": "Target boule sits directly behind one obstacle. Shoot straight through.",
        "legend": [
            {"color": "#ff9800", "label": "Target"},
            {"color": "#78909c", "label": "Obstacle"},
        ],
        # Reference image: 1000013536.png
        # Orange boule behind a single grey boule, blue arrow from top-centre
        "svg": """<svg width="90" height="72" viewBox="0 0 90 72" fill="none" xmlns="http://www.w3.org/2000/svg">
  <!-- Ground ellipse -->
  <ellipse cx="45" cy="62" rx="26" ry="6" fill="none" stroke="#d1d5db" stroke-width="1.5" stroke-dasharray="4,3"/>
  <!-- Target boule (orange, partially behind obstacle) -->
  <circle cx="45" cy="46" r="14" fill="#ff9800" stroke="#e65100" stroke-width="2"/>
  <circle cx="41" cy="41" r="4" fill="rgba(255,255,255,0.35)"/>
  <!-- Obstacle boule (grey, in front) -->
  <circle cx="45" cy="30" r="13" fill="#78909c" stroke="#455a64" stroke-width="2"/>
  <circle cx="41" cy="26" r="3.5" fill="rgba(255,255,255,0.30)"/>
  <!-- Shot arrow -->
  <line x1="45" y1="6" x2="45" y2="14" stroke="#1a56db" stroke-width="2.5" marker-end="url(#ht1)"/>
  <defs><marker id="ht1" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="#1a56db"/></marker></defs>
</svg>""",
        "pts": [0, 1, 3, 5],
    },
    {
        "number": 2,
        "label": "Flanked — Two Obstacles",
        "short": "2 Flank",
        "icon": "↔️",
        "description": "Target boule flanked by two grey obstacles. Shoot through the gap.",
        "legend": [
            {"color": "#ff9800", "label": "Target"},
            {"color": "#78909c", "label": "Obstacles"},
        ],
        # Reference image: 1000013537.png
        # Orange boule between two grey boules, blue arrow from top-centre
        "svg": """<svg width="90" height="72" viewBox="0 0 90 72" fill="none" xmlns="http://www.w3.org/2000/svg">
  <!-- Ground ellipse -->
  <ellipse cx="45" cy="62" rx="30" ry="6" fill="none" stroke="#d1d5db" stroke-width="1.5" stroke-dasharray="4,3"/>
  <!-- Left obstacle -->
  <circle cx="24" cy="44" r="13" fill="#78909c" stroke="#455a64" stroke-width="2"/>
  <circle cx="20" cy="40" r="3.5" fill="rgba(255,255,255,0.30)"/>
  <!-- Right obstacle -->
  <circle cx="66" cy="44" r="13" fill="#78909c" stroke="#455a64" stroke-width="2"/>
  <circle cx="62" cy="40" r="3.5" fill="rgba(255,255,255,0.30)"/>
  <!-- Target boule (orange, centre) -->
  <circle cx="45" cy="42" r="12" fill="#ff9800" stroke="#e65100" stroke-width="2"/>
  <circle cx="41" cy="38" r="3.5" fill="rgba(255,255,255,0.35)"/>
  <!-- Shot arrow -->
  <line x1="45" y1="6" x2="45" y2="26" stroke="#1a56db" stroke-width="2.5" marker-end="url(#ht2)"/>
  <defs><marker id="ht2" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="#1a56db"/></marker></defs>
</svg>""",
        "pts": [0, 1, 3, 5],
    },
    {
        "number": 3,
        "label": "Cluster — Three Obstacles",
        "short": "3 Cluster",
        "icon": "🔍",
        "description": "Target boule hidden in a cluster of three grey boules. Find the angle.",
        "legend": [
            {"color": "#ff9800", "label": "Target"},
            {"color": "#78909c", "label": "Cluster"},
        ],
        # Reference image: 1000013540.png
        # Orange boule partially visible behind a cluster of 3 grey boules
        "svg": """<svg width="90" height="72" viewBox="0 0 90 72" fill="none" xmlns="http://www.w3.org/2000/svg">
  <!-- Ground ellipse -->
  <ellipse cx="45" cy="64" rx="30" ry="6" fill="none" stroke="#d1d5db" stroke-width="1.5" stroke-dasharray="4,3"/>
  <!-- Target boule (orange, top-left, partially hidden) -->
  <circle cx="38" cy="34" r="13" fill="#ff9800" stroke="#e65100" stroke-width="2"/>
  <circle cx="34" cy="30" r="3.5" fill="rgba(255,255,255,0.35)"/>
  <!-- Front-left obstacle -->
  <circle cx="28" cy="50" r="13" fill="#78909c" stroke="#455a64" stroke-width="2"/>
  <circle cx="24" cy="46" r="3.5" fill="rgba(255,255,255,0.30)"/>
  <!-- Front-centre obstacle -->
  <circle cx="48" cy="52" r="13" fill="#78909c" stroke="#455a64" stroke-width="2"/>
  <circle cx="44" cy="48" r="3.5" fill="rgba(255,255,255,0.30)"/>
  <!-- Front-right obstacle (smaller, partially visible) -->
  <circle cx="66" cy="46" r="11" fill="#78909c" stroke="#455a64" stroke-width="1.5"/>
  <circle cx="63" cy="43" r="3" fill="rgba(255,255,255,0.28)"/>
  <!-- Shot arrow (angled from top-left) -->
  <line x1="18" y1="10" x2="30" y2="22" stroke="#1a56db" stroke-width="2.5" marker-end="url(#ht3)"/>
  <defs><marker id="ht3" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="#1a56db"/></marker></defs>
</svg>""",
        "pts": [0, 1, 3, 5],
    },
    {
        "number": 4,
        "label": "Angled Approach",
        "short": "4 Angle",
        "icon": "↪️",
        "description": "Target boule offset to the right. Shoot at an angle to reach it.",
        "legend": [
            {"color": "#ff9800", "label": "Target"},
            {"color": "#78909c", "label": "Obstacle"},
        ],
        # Reference image: 1000013539.png
        # Orange boule offset/angled behind a grey boule, blue arrow from top-left
        "svg": """<svg width="90" height="72" viewBox="0 0 90 72" fill="none" xmlns="http://www.w3.org/2000/svg">
  <!-- Ground ellipse -->
  <ellipse cx="50" cy="62" rx="28" ry="6" fill="none" stroke="#d1d5db" stroke-width="1.5" stroke-dasharray="4,3"/>
  <!-- Target boule (orange, right side) -->
  <circle cx="57" cy="46" r="14" fill="#ff9800" stroke="#e65100" stroke-width="2"/>
  <circle cx="53" cy="41" r="4" fill="rgba(255,255,255,0.35)"/>
  <!-- Obstacle boule (grey, front-left) -->
  <circle cx="40" cy="38" r="13" fill="#78909c" stroke="#455a64" stroke-width="2"/>
  <circle cx="36" cy="34" r="3.5" fill="rgba(255,255,255,0.30)"/>
  <!-- Shot arrow (angled from top-left) -->
  <line x1="16" y1="10" x2="30" y2="24" stroke="#1a56db" stroke-width="2.5" marker-end="url(#ht4)"/>
  <defs><marker id="ht4" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="#1a56db"/></marker></defs>
</svg>""",
        "pts": [0, 1, 3, 5],
    },
    {
        "number": 5,
        "label": "Deep Cover — Row of Three",
        "short": "5 Deep",
        "icon": "🛡️",
        "description": "Target boule hidden behind a row of three obstacles. Precision required.",
        "legend": [
            {"color": "#ff9800", "label": "Target"},
            {"color": "#78909c", "label": "Row"},
        ],
        # Reference image: 1000013538.png
        # Orange boule behind a row of 3 grey boules, blue arrow from top-centre
        "svg": """<svg width="90" height="72" viewBox="0 0 90 72" fill="none" xmlns="http://www.w3.org/2000/svg">
  <!-- Ground ellipse -->
  <ellipse cx="45" cy="64" rx="34" ry="6" fill="none" stroke="#d1d5db" stroke-width="1.5" stroke-dasharray="4,3"/>
  <!-- Target boule (orange, behind centre of row) -->
  <circle cx="45" cy="38" r="11" fill="#ff9800" stroke="#e65100" stroke-width="2"/>
  <circle cx="42" cy="34" r="3" fill="rgba(255,255,255,0.35)"/>
  <!-- Left obstacle -->
  <circle cx="20" cy="52" r="13" fill="#78909c" stroke="#455a64" stroke-width="2"/>
  <circle cx="16" cy="48" r="3.5" fill="rgba(255,255,255,0.30)"/>
  <!-- Centre obstacle (directly in front of target) -->
  <circle cx="45" cy="52" r="13" fill="#78909c" stroke="#455a64" stroke-width="2"/>
  <circle cx="41" cy="48" r="3.5" fill="rgba(255,255,255,0.30)"/>
  <!-- Right obstacle -->
  <circle cx="70" cy="52" r="13" fill="#78909c" stroke="#455a64" stroke-width="2"/>
  <circle cx="66" cy="48" r="3.5" fill="rgba(255,255,255,0.30)"/>
  <!-- Shot arrow -->
  <line x1="45" y1="6" x2="45" y2="23" stroke="#1a56db" stroke-width="2.5" marker-end="url(#ht5)"/>
  <defs><marker id="ht5" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="#1a56db"/></marker></defs>
</svg>""",
        "pts": [0, 1, 3, 5],
    },
]
