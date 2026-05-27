"""
Sequence Drill Scenarios
========================
First scenario-pack for the Sequence Drill drill type.

Mirrors the exact data structure of TACTICAL_ATELIERS so the engine,
session flow, scoring, and UI shell are 100% reused without modification.

5 ateliers × 4 shots = 20 shots per session.
Scoring: Carreau 5 pts / Petit Carreau 3 pts / Hit 1 pt / Miss 0 pts.

Each atelier has:
  - A rich SVG diagram communicating the drill visually (arrows, numbers, highlights)
  - A single short instruction line (≤ 8 words)
  - A legend for the colour key
  - pts: [miss, hit, petit_carreau, carreau] point values
"""

# ── Shared SVG arrow marker defs ──────────────────────────────────────────────
# Each SVG embeds its own <defs> to stay self-contained (no shared DOM IDs).

SEQUENCE_ATELIERS = [
    # ── Atelier 1 ─────────────────────────────────────────────────────────────
    # 4 boules in a horizontal line, shoot left → right in order.
    # Visual: 4 grey boules in a row, blue numbered circles 1-4 above each,
    #         a right-pointing arrow sweeping across all four.
    {
        'number': 1,
        'name': 'Atelier 1',
        'label': 'Left to Right — Horizontal Line',
        'description': 'Hit all 4 boules from left to right.',
        'icon': '➡️',
        'has_jack_target': False,
        'legend': [
            {'color': '#9e9e9e', 'label': 'Target boule'},
            {'color': '#1a56db', 'label': 'Shot order'},
        ],
        # SVG: 4 boules at y=38, x = 10, 28, 46, 64
        # Numbered badges 1-4 above each boule
        # Sweep arrow from left of boule-1 to right of boule-4
        'svg': '''<svg width="80" height="64" viewBox="0 0 80 64" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="sq1-arr" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
      <path d="M0,0 L7,3.5 L0,7 Z" fill="#1a56db"/>
    </marker>
  </defs>
  <!-- Sweep arrow -->
  <line x1="4" y1="38" x2="72" y2="38" stroke="#1a56db" stroke-width="1.8" marker-end="url(#sq1-arr)" stroke-dasharray="3,2"/>
  <!-- Boule 1 -->
  <circle cx="12" cy="38" r="8" fill="#bdbdbd" stroke="#757575" stroke-width="1.5"/>
  <circle cx="10" cy="36" r="2.2" fill="rgba(255,255,255,0.55)"/>
  <!-- Boule 2 -->
  <circle cx="30" cy="38" r="8" fill="#bdbdbd" stroke="#757575" stroke-width="1.5"/>
  <circle cx="28" cy="36" r="2.2" fill="rgba(255,255,255,0.55)"/>
  <!-- Boule 3 -->
  <circle cx="50" cy="38" r="8" fill="#bdbdbd" stroke="#757575" stroke-width="1.5"/>
  <circle cx="48" cy="36" r="2.2" fill="rgba(255,255,255,0.55)"/>
  <!-- Boule 4 -->
  <circle cx="68" cy="38" r="8" fill="#bdbdbd" stroke="#757575" stroke-width="1.5"/>
  <circle cx="66" cy="36" r="2.2" fill="rgba(255,255,255,0.55)"/>
  <!-- Number badges -->
  <circle cx="12" cy="22" r="7" fill="#1a56db"/>
  <text x="12" y="26" text-anchor="middle" font-size="8" font-weight="bold" fill="white">1</text>
  <circle cx="30" cy="22" r="7" fill="#1a56db"/>
  <text x="30" y="26" text-anchor="middle" font-size="8" font-weight="bold" fill="white">2</text>
  <circle cx="50" cy="22" r="7" fill="#1a56db"/>
  <text x="50" y="26" text-anchor="middle" font-size="8" font-weight="bold" fill="white">3</text>
  <circle cx="68" cy="22" r="7" fill="#1a56db"/>
  <text x="68" y="26" text-anchor="middle" font-size="8" font-weight="bold" fill="white">4</text>
  <!-- Connector lines from badge to boule -->
  <line x1="12" y1="29" x2="12" y2="30" stroke="#1a56db" stroke-width="1"/>
  <line x1="30" y1="29" x2="30" y2="30" stroke="#1a56db" stroke-width="1"/>
  <line x1="50" y1="29" x2="50" y2="30" stroke="#1a56db" stroke-width="1"/>
  <line x1="68" y1="29" x2="68" y2="30" stroke="#1a56db" stroke-width="1"/>
  <!-- Ground line -->
  <line x1="2" y1="56" x2="78" y2="56" stroke="#e5e7eb" stroke-width="1"/>
</svg>''',
        'pts': [0, 1, 3, 5],
    },

    # ── Atelier 2 ─────────────────────────────────────────────────────────────
    # 8 boules in a horizontal line, hit only the alternating (odd) ones.
    # Visual: 8 boules, odd positions highlighted in amber, even positions grey/dim.
    #         Target boules have a glowing ring; non-targets are visually muted.
    {
        'number': 2,
        'name': 'Atelier 2',
        'label': 'Alternating Targets — Skip the Even',
        'description': 'Hit only the marked boules.',
        'icon': '🔶',
        'has_jack_target': False,
        'legend': [
            {'color': '#f59e0b', 'label': 'Target boule'},
            {'color': '#d1d5db', 'label': 'Skip (non-target)'},
        ],
        # 8 boules at y=40, x = 6,15,24,33,42,51,60,69 (spacing 9px)
        # Targets: positions 1,3,5,7 (x=6,24,42,60) — amber with ring
        # Non-targets: positions 2,4,6,8 (x=15,33,51,69) — light grey, dimmed
        'svg': '''<svg width="80" height="64" viewBox="0 0 80 64" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="sq2-arr" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
      <path d="M0,0 L7,3.5 L0,7 Z" fill="#f59e0b"/>
    </marker>
  </defs>
  <!-- Non-target boules (dim) -->
  <circle cx="15" cy="40" r="6" fill="#e5e7eb" stroke="#d1d5db" stroke-width="1.2" opacity="0.5"/>
  <circle cx="33" cy="40" r="6" fill="#e5e7eb" stroke="#d1d5db" stroke-width="1.2" opacity="0.5"/>
  <circle cx="51" cy="40" r="6" fill="#e5e7eb" stroke="#d1d5db" stroke-width="1.2" opacity="0.5"/>
  <circle cx="69" cy="40" r="6" fill="#e5e7eb" stroke="#d1d5db" stroke-width="1.2" opacity="0.5"/>
  <!-- Target boules (highlighted amber) with outer ring -->
  <circle cx="6" cy="40" r="8.5" fill="none" stroke="#fcd34d" stroke-width="1.5" stroke-dasharray="3,2"/>
  <circle cx="6" cy="40" r="6" fill="#f59e0b" stroke="#d97706" stroke-width="1.5"/>
  <circle cx="4.5" cy="38" r="1.8" fill="rgba(255,255,255,0.55)"/>
  <circle cx="24" cy="40" r="8.5" fill="none" stroke="#fcd34d" stroke-width="1.5" stroke-dasharray="3,2"/>
  <circle cx="24" cy="40" r="6" fill="#f59e0b" stroke="#d97706" stroke-width="1.5"/>
  <circle cx="22.5" cy="38" r="1.8" fill="rgba(255,255,255,0.55)"/>
  <circle cx="42" cy="40" r="8.5" fill="none" stroke="#fcd34d" stroke-width="1.5" stroke-dasharray="3,2"/>
  <circle cx="42" cy="40" r="6" fill="#f59e0b" stroke="#d97706" stroke-width="1.5"/>
  <circle cx="40.5" cy="38" r="1.8" fill="rgba(255,255,255,0.55)"/>
  <circle cx="60" cy="40" r="8.5" fill="none" stroke="#fcd34d" stroke-width="1.5" stroke-dasharray="3,2"/>
  <circle cx="60" cy="40" r="6" fill="#f59e0b" stroke="#d97706" stroke-width="1.5"/>
  <circle cx="58.5" cy="38" r="1.8" fill="rgba(255,255,255,0.55)"/>
  <!-- "SKIP" X marks on non-targets -->
  <line x1="12" y1="37" x2="18" y2="43" stroke="#9ca3af" stroke-width="1.2" opacity="0.6"/>
  <line x1="18" y1="37" x2="12" y2="43" stroke="#9ca3af" stroke-width="1.2" opacity="0.6"/>
  <line x1="30" y1="37" x2="36" y2="43" stroke="#9ca3af" stroke-width="1.2" opacity="0.6"/>
  <line x1="36" y1="37" x2="30" y2="43" stroke="#9ca3af" stroke-width="1.2" opacity="0.6"/>
  <line x1="48" y1="37" x2="54" y2="43" stroke="#9ca3af" stroke-width="1.2" opacity="0.6"/>
  <line x1="54" y1="37" x2="48" y2="43" stroke="#9ca3af" stroke-width="1.2" opacity="0.6"/>
  <line x1="66" y1="37" x2="72" y2="43" stroke="#9ca3af" stroke-width="1.2" opacity="0.6"/>
  <line x1="72" y1="37" x2="66" y2="43" stroke="#9ca3af" stroke-width="1.2" opacity="0.6"/>
  <!-- Sweep arrow above targets -->
  <line x1="2" y1="22" x2="64" y2="22" stroke="#f59e0b" stroke-width="1.5" marker-end="url(#sq2-arr)" stroke-dasharray="4,3"/>
  <!-- Ground line -->
  <line x1="2" y1="56" x2="78" y2="56" stroke="#e5e7eb" stroke-width="1"/>
</svg>''',
        'pts': [0, 1, 3, 5],
    },

    # ── Atelier 3 ─────────────────────────────────────────────────────────────
    # 4 boules in a vertical line (far to near), start from the BACK (top) boule.
    # Visual: 4 boules stacked vertically, numbered 1-4 top to bottom,
    #         downward arrow indicating direction of play (back → front).
    {
        'number': 3,
        'name': 'Atelier 3',
        'label': 'Back to Front — Vertical Line',
        'description': 'Start from the back boule.',
        'icon': '⬇️',
        'has_jack_target': False,
        'legend': [
            {'color': '#9e9e9e', 'label': 'Target boule'},
            {'color': '#1a56db', 'label': 'Shot order (back→front)'},
        ],
        # 4 boules at x=40, y = 8, 22, 36, 50 (spacing 14px)
        # Numbered badges 1-4 to the right of each boule
        # Downward arrow on the left side
        'svg': '''<svg width="80" height="64" viewBox="0 0 80 64" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="sq3-arr" markerWidth="7" markerHeight="7" refX="3.5" refY="6" orient="auto">
      <path d="M0,0 L7,0 L3.5,7 Z" fill="#1a56db"/>
    </marker>
  </defs>
  <!-- Direction arrow (left side, top to bottom) -->
  <line x1="14" y1="6" x2="14" y2="54" stroke="#1a56db" stroke-width="1.8" marker-end="url(#sq3-arr)" stroke-dasharray="3,2"/>
  <!-- FAR label at top -->
  <text x="14" y="5" text-anchor="middle" font-size="6" fill="#6b7280">FAR</text>
  <!-- NEAR label at bottom -->
  <text x="14" y="62" text-anchor="middle" font-size="6" fill="#6b7280">NEAR</text>
  <!-- Boule 1 (back/far) -->
  <circle cx="40" cy="10" r="7" fill="#bdbdbd" stroke="#757575" stroke-width="1.5"/>
  <circle cx="38" cy="8" r="2" fill="rgba(255,255,255,0.55)"/>
  <!-- Boule 2 -->
  <circle cx="40" cy="24" r="7" fill="#bdbdbd" stroke="#757575" stroke-width="1.5"/>
  <circle cx="38" cy="22" r="2" fill="rgba(255,255,255,0.55)"/>
  <!-- Boule 3 -->
  <circle cx="40" cy="38" r="7" fill="#bdbdbd" stroke="#757575" stroke-width="1.5"/>
  <circle cx="38" cy="36" r="2" fill="rgba(255,255,255,0.55)"/>
  <!-- Boule 4 (front/near) -->
  <circle cx="40" cy="52" r="7" fill="#bdbdbd" stroke="#757575" stroke-width="1.5"/>
  <circle cx="38" cy="50" r="2" fill="rgba(255,255,255,0.55)"/>
  <!-- Number badges (right side) -->
  <circle cx="62" cy="10" r="7" fill="#1a56db"/>
  <text x="62" y="14" text-anchor="middle" font-size="8" font-weight="bold" fill="white">1</text>
  <circle cx="62" cy="24" r="7" fill="#1a56db"/>
  <text x="62" y="28" text-anchor="middle" font-size="8" font-weight="bold" fill="white">2</text>
  <circle cx="62" cy="38" r="7" fill="#1a56db"/>
  <text x="62" y="42" text-anchor="middle" font-size="8" font-weight="bold" fill="white">3</text>
  <circle cx="62" cy="52" r="7" fill="#1a56db"/>
  <text x="62" y="56" text-anchor="middle" font-size="8" font-weight="bold" fill="white">4</text>
  <!-- Connector lines from boule to badge -->
  <line x1="47" y1="10" x2="55" y2="10" stroke="#1a56db" stroke-width="0.8" stroke-dasharray="2,2"/>
  <line x1="47" y1="24" x2="55" y2="24" stroke="#1a56db" stroke-width="0.8" stroke-dasharray="2,2"/>
  <line x1="47" y1="38" x2="55" y2="38" stroke="#1a56db" stroke-width="0.8" stroke-dasharray="2,2"/>
  <line x1="47" y1="52" x2="55" y2="52" stroke="#1a56db" stroke-width="0.8" stroke-dasharray="2,2"/>
</svg>''',
        'pts': [0, 1, 3, 5],
    },

    # ── Atelier 4 ─────────────────────────────────────────────────────────────
    # 4 boules in a vertical line, start from the FRONT boule.
    # Hit the SIDE of the front boule so it exits LEFT or RIGHT — not straight.
    # Visual: front boule highlighted in red, side-impact indicator (angled arrow),
    #         left/right exit arrows, rear boules dimmed with a "do not hit" indicator.
    {
        'number': 4,
        'name': 'Atelier 4',
        'label': 'Side Exit — Directional Control',
        'description': 'Hit the side so the boule exits left or right.',
        'icon': '↔️',
        'has_jack_target': False,
        'legend': [
            {'color': '#ef4444', 'label': 'Target (front boule)'},
            {'color': '#9e9e9e', 'label': 'Rear boules (avoid)'},
            {'color': '#10b981', 'label': 'Exit direction'},
        ],
        # Front boule at y=52 (near), rear boules at y=38,24,10 (far)
        # Angled impact arrow from upper-left → front boule side
        # Green exit arrows pointing left and right from front boule
        # Rear boules dimmed
        'svg': '''<svg width="80" height="64" viewBox="0 0 80 64" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="sq4-impact" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
      <path d="M0,0 L7,3.5 L0,7 Z" fill="#1a56db"/>
    </marker>
    <marker id="sq4-exit-l" markerWidth="7" markerHeight="7" refX="1" refY="3.5" orient="auto">
      <path d="M7,0 L0,3.5 L7,7 Z" fill="#10b981"/>
    </marker>
    <marker id="sq4-exit-r" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
      <path d="M0,0 L7,3.5 L0,7 Z" fill="#10b981"/>
    </marker>
  </defs>
  <!-- Rear boules (dimmed) -->
  <circle cx="40" cy="10" r="7" fill="#e5e7eb" stroke="#d1d5db" stroke-width="1.2" opacity="0.45"/>
  <circle cx="40" cy="24" r="7" fill="#e5e7eb" stroke="#d1d5db" stroke-width="1.2" opacity="0.45"/>
  <circle cx="40" cy="38" r="7" fill="#e5e7eb" stroke="#d1d5db" stroke-width="1.2" opacity="0.45"/>
  <!-- "Do not continue" barrier line between front and rear -->
  <line x1="26" y1="44" x2="54" y2="44" stroke="#ef4444" stroke-width="1.2" stroke-dasharray="3,2" opacity="0.6"/>
  <!-- Front boule (target — red highlight) -->
  <circle cx="40" cy="54" r="8.5" fill="none" stroke="#fca5a5" stroke-width="1.5" stroke-dasharray="3,2"/>
  <circle cx="40" cy="54" r="7" fill="#ef4444" stroke="#dc2626" stroke-width="1.5"/>
  <circle cx="38" cy="52" r="2" fill="rgba(255,255,255,0.5)"/>
  <!-- Impact arrow: angled from upper-left → left side of front boule -->
  <line x1="20" y1="40" x2="33" y2="52" stroke="#1a56db" stroke-width="2" marker-end="url(#sq4-impact)"/>
  <!-- Exit arrow LEFT -->
  <line x1="30" y1="54" x2="8" y2="54" stroke="#10b981" stroke-width="2" marker-end="url(#sq4-exit-l)"/>
  <!-- Exit arrow RIGHT -->
  <line x1="50" y1="54" x2="72" y2="54" stroke="#10b981" stroke-width="2" marker-end="url(#sq4-exit-r)"/>
  <!-- Side impact label -->
  <text x="14" y="50" text-anchor="middle" font-size="6" fill="#1a56db" font-weight="bold">SIDE</text>
  <!-- Exit labels -->
  <text x="8" y="62" text-anchor="middle" font-size="5.5" fill="#10b981">EXIT</text>
  <text x="72" y="62" text-anchor="middle" font-size="5.5" fill="#10b981">EXIT</text>
</svg>''',
        'pts': [0, 1, 3, 5],
    },

    # ── Atelier 5 ─────────────────────────────────────────────────────────────
    # 2 horizontal rows of boules (front row × 3, rear row × 3).
    # Hit ONLY the rear row boules; front row is a protective barrier.
    # Visual: rear row highlighted in amber with numbered badges,
    #         front row dimmed with a "shield" / barrier indicator.
    {
        'number': 5,
        'name': 'Atelier 5',
        'label': 'Rear Row Only — Over the Guard',
        'description': 'Hit only the back-row boules.',
        'icon': '🎯',
        'has_jack_target': False,
        'legend': [
            {'color': '#f59e0b', 'label': 'Rear targets (hit these)'},
            {'color': '#d1d5db', 'label': 'Front guard (avoid)'},
        ],
        # Front row: 3 boules at y=50, x=20,40,60
        # Rear row:  3 boules at y=28, x=20,40,60
        # Numbered badges 1-3 above rear row
        # Curved "over the top" trajectory arc from shooter side to rear row
        'svg': '''<svg width="80" height="64" viewBox="0 0 80 64" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="sq5-arr" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
      <path d="M0,0 L7,3.5 L0,7 Z" fill="#f59e0b"/>
    </marker>
  </defs>
  <!-- Front row (guard / dim) -->
  <circle cx="20" cy="50" r="7" fill="#e5e7eb" stroke="#d1d5db" stroke-width="1.5" opacity="0.55"/>
  <circle cx="40" cy="50" r="7" fill="#e5e7eb" stroke="#d1d5db" stroke-width="1.5" opacity="0.55"/>
  <circle cx="60" cy="50" r="7" fill="#e5e7eb" stroke="#d1d5db" stroke-width="1.5" opacity="0.55"/>
  <!-- Guard label -->
  <text x="40" y="62" text-anchor="middle" font-size="6" fill="#9ca3af">GUARD</text>
  <!-- Barrier line between rows -->
  <line x1="6" y1="40" x2="74" y2="40" stroke="#d1d5db" stroke-width="1" stroke-dasharray="4,3"/>
  <!-- Rear row (targets — amber) with outer ring -->
  <circle cx="20" cy="28" r="9" fill="none" stroke="#fcd34d" stroke-width="1.5" stroke-dasharray="3,2"/>
  <circle cx="20" cy="28" r="7" fill="#f59e0b" stroke="#d97706" stroke-width="1.5"/>
  <circle cx="18" cy="26" r="2" fill="rgba(255,255,255,0.55)"/>
  <circle cx="40" cy="28" r="9" fill="none" stroke="#fcd34d" stroke-width="1.5" stroke-dasharray="3,2"/>
  <circle cx="40" cy="28" r="7" fill="#f59e0b" stroke="#d97706" stroke-width="1.5"/>
  <circle cx="38" cy="26" r="2" fill="rgba(255,255,255,0.55)"/>
  <circle cx="60" cy="28" r="9" fill="none" stroke="#fcd34d" stroke-width="1.5" stroke-dasharray="3,2"/>
  <circle cx="60" cy="28" r="7" fill="#f59e0b" stroke="#d97706" stroke-width="1.5"/>
  <circle cx="58" cy="26" r="2" fill="rgba(255,255,255,0.55)"/>
  <!-- Number badges above rear row -->
  <circle cx="20" cy="12" r="6" fill="#1a56db"/>
  <text x="20" y="16" text-anchor="middle" font-size="7.5" font-weight="bold" fill="white">1</text>
  <circle cx="40" cy="12" r="6" fill="#1a56db"/>
  <text x="40" y="16" text-anchor="middle" font-size="7.5" font-weight="bold" fill="white">2</text>
  <circle cx="60" cy="12" r="6" fill="#1a56db"/>
  <text x="60" y="16" text-anchor="middle" font-size="7.5" font-weight="bold" fill="white">3</text>
  <!-- Curved "over the top" trajectory arc (shooter → rear row) -->
  <path d="M4,56 Q4,4 20,20" stroke="#f59e0b" stroke-width="1.5" fill="none" stroke-dasharray="3,2" marker-end="url(#sq5-arr)"/>
</svg>''',
        'pts': [0, 1, 3, 5],
    },
]
