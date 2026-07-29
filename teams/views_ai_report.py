"""
AI Coach Report Generator — v2
================================
Generates a dense structured PDF performance dossier for a PFC player.
Optimised for AI readability (petA UMP) and human coaching analysis.

Accessible via: /teams/players/<player_id>/ai-coach-report/
Only the player themselves (session match) or staff can download.

Section map
-----------
  0  AI Reader Instructions (verbatim — selectable text)
  1  Player Identity & Overview
  2  Rating Evolution & Trend Analysis  (chart + full history table)
  3  Tournament Match History  (with full lineup: names + roles)
  4  Score Progression Analysis  (per-match step charts + match-flow fields)
  5  Match-Flow Aggregate  (comeback / close-game / collapse summary)
  6  Teammate Statistics  (per-teammate W/L, win%, rating change, roles)
  7  Opponent Statistics  (per-opponent W/L, win%, score diff)
  8  Role & Format Breakdown  (from MatchPlayer + PlayerProfile helpers)
  9  Tournament Breakdown  (per-tournament W/L, win%, avg score)
 10  Friendly Game Breakdown  (total, W/L, per-game table)
 11  Practice Data  (shooting + pointing bar charts, session table, flagged sessions)
 12  Data Quality Notes  (discrepancy flags for the AI reader)
"""

import io
import math
from collections import defaultdict
from datetime import datetime, timezone as dt_timezone

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image, KeepTogether, PageBreak
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

from .models import Player, PlayerProfile

# ─────────────────────────────────────────────────────────────────────────────
# Colour palette
# ─────────────────────────────────────────────────────────────────────────────
C_BG_DARK   = colors.HexColor('#0f172a')
C_BG_MID    = colors.HexColor('#1e293b')
C_BG_LIGHT  = colors.HexColor('#f1f5f9')
C_ACCENT    = colors.HexColor('#3b82f6')
C_GREEN     = colors.HexColor('#10b981')
C_RED       = colors.HexColor('#ef4444')
C_YELLOW    = colors.HexColor('#f59e0b')
C_TEXT_DARK = colors.HexColor('#0f172a')
C_TEXT_LIGHT= colors.white
C_BORDER    = colors.HexColor('#cbd5e1')

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm


# ─────────────────────────────────────────────────────────────────────────────
# Style helpers
# ─────────────────────────────────────────────────────────────────────────────
def _styles():
    base = getSampleStyleSheet()
    def s(name, **kw):
        return ParagraphStyle(name, parent=base['Normal'], **kw)
    return {
        'cover_title': s('cover_title', fontSize=22, textColor=C_TEXT_LIGHT,
                         fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=4),
        'cover_sub':   s('cover_sub', fontSize=11, textColor=colors.HexColor('#94a3b8'),
                         fontName='Helvetica', alignment=TA_CENTER, spaceAfter=2),
        'cover_disc':  s('cover_disc', fontSize=8, textColor=colors.HexColor('#64748b'),
                         fontName='Helvetica-Oblique', alignment=TA_CENTER, spaceAfter=0),
        'section_hdr': s('section_hdr', fontSize=11, textColor=C_TEXT_LIGHT,
                         fontName='Helvetica-Bold', alignment=TA_LEFT,
                         leftIndent=4, spaceAfter=0),
        'label':       s('label', fontSize=8, textColor=colors.HexColor('#64748b'),
                         fontName='Helvetica-Bold', spaceAfter=1),
        'value':       s('value', fontSize=9, textColor=C_TEXT_DARK,
                         fontName='Helvetica', spaceAfter=2),
        'mono':        s('mono', fontSize=8, textColor=C_TEXT_DARK,
                         fontName='Courier', spaceAfter=1),
        'body':        s('body', fontSize=8.5, textColor=C_TEXT_DARK,
                         fontName='Helvetica', spaceAfter=3, leading=12),
        'body_bold':   s('body_bold', fontSize=8.5, textColor=C_TEXT_DARK,
                         fontName='Helvetica-Bold', spaceAfter=3, leading=12),
        'caption':     s('caption', fontSize=7.5, textColor=colors.HexColor('#64748b'),
                         fontName='Helvetica-Oblique', alignment=TA_CENTER, spaceAfter=2),
        'th':          s('th', fontSize=8, textColor=C_TEXT_LIGHT,
                         fontName='Helvetica-Bold', alignment=TA_CENTER),
        'td':          s('td', fontSize=8, textColor=C_TEXT_DARK,
                         fontName='Helvetica', alignment=TA_CENTER),
        'td_left':     s('td_left', fontSize=8, textColor=C_TEXT_DARK,
                         fontName='Helvetica', alignment=TA_LEFT),
        'instr_head':  s('instr_head', fontSize=10, textColor=C_TEXT_DARK,
                         fontName='Helvetica-Bold', spaceAfter=4, spaceBefore=6),
        'instr_body':  s('instr_body', fontSize=8.5, textColor=C_TEXT_DARK,
                         fontName='Helvetica', spaceAfter=3, leading=13),
        'instr_item':  s('instr_item', fontSize=8.5, textColor=C_TEXT_DARK,
                         fontName='Helvetica', spaceAfter=2, leading=13, leftIndent=12),
    }


def _section_header(title, ST):
    p = Paragraph(f"▌  {title}", ST['section_hdr'])
    tbl = Table([[p]], colWidths=[PAGE_W - 2 * MARGIN])
    tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), C_BG_MID),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
    ]))
    return [tbl, Spacer(1, 4)]


def _kv_table(pairs, ST, cols=3):
    cells = []
    for label, val in pairs:
        cells.append([
            Paragraph(label, ST['label']),
            Paragraph(str(val), ST['value'])
        ])
    while len(cells) % cols != 0:
        cells.append([Paragraph('', ST['label']), Paragraph('', ST['value'])])
    col_w = (PAGE_W - 2 * MARGIN) / cols
    rows = [cells[i:i+cols] for i in range(0, len(cells), cols)]
    flat = [[cell for pair in row for cell in pair] for row in rows]
    col_widths = [col_w * 0.38, col_w * 0.62] * cols
    tbl = Table(flat, colWidths=col_widths)
    tbl.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
        ('LINEBELOW',     (0, 0), (-1, -2), 0.3, C_BORDER),
    ]))
    return tbl


def _data_table(headers, rows, ST, col_widths=None):
    header_row = [Paragraph(h, ST['th']) for h in headers]
    body_rows = []
    for i, row in enumerate(rows):
        styled = []
        for j, cell in enumerate(row):
            style = ST['td_left'] if j == 0 else ST['td']
            styled.append(Paragraph(str(cell), style))
        body_rows.append(styled)
    all_rows = [header_row] + body_rows
    if col_widths is None:
        n = len(headers)
        col_widths = [(PAGE_W - 2 * MARGIN) / n] * n
    tbl = Table(all_rows, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ('BACKGROUND',    (0, 0), (-1, 0),  C_BG_MID),
        ('TEXTCOLOR',     (0, 0), (-1, 0),  C_TEXT_LIGHT),
        ('FONTNAME',      (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, 0),  8),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
        ('GRID',          (0, 0), (-1, -1), 0.3, C_BORDER),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]
    for i in range(1, len(all_rows)):
        if i % 2 == 0:
            style_cmds.append(('BACKGROUND', (0, i), (-1, i), C_BG_LIGHT))
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


def _matplotlib_to_image(fig, width_mm=170):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    img = Image(buf, width=width_mm * mm)
    img.hAlign = 'CENTER'
    return img


# ─────────────────────────────────────────────────────────────────────────────
# Chart builders
# ─────────────────────────────────────────────────────────────────────────────
def _build_rating_chart(history):
    """Line chart of rating evolution — green/red per-segment colouring."""
    fig, ax = plt.subplots(figsize=(10, 2.8), facecolor='#0f172a')
    ax.set_facecolor('#1e293b')

    values = [100.0] + [e.get('new_value', 100.0) for e in history]
    labels = ['Start'] + [
        _parse_ts(e.get('timestamp', '')).strftime('%b %d')
        if _parse_ts(e.get('timestamp', '')) else f'M{i+1}'
        for i, e in enumerate(history)
    ]
    x = list(range(len(values)))

    # Per-segment colour
    for i in range(1, len(values)):
        c = '#10b981' if values[i] >= values[i-1] else '#ef4444'
        ax.plot([x[i-1], x[i]], [values[i-1], values[i]], color=c, linewidth=1.5)

    ax.fill_between(x, values, min(values) - 5, alpha=0.10, color='#3b82f6')
    ax.axhline(100.0, color='#64748b', linewidth=0.7, linestyle='--', label='Baseline (100)')

    # Peak and trough annotations
    if len(values) > 1:
        peak_i = int(np.argmax(values))
        trough_i = int(np.argmin(values))
        ax.annotate(f'Peak {values[peak_i]:.1f}',
                    xy=(x[peak_i], values[peak_i]),
                    xytext=(0, 6), textcoords='offset points',
                    color='#10b981', fontsize=6.5, ha='center')
        ax.annotate(f'Low {values[trough_i]:.1f}',
                    xy=(x[trough_i], values[trough_i]),
                    xytext=(0, -10), textcoords='offset points',
                    color='#ef4444', fontsize=6.5, ha='center')

    step = max(1, len(x) // 10)
    ax.set_xticks(x[::step])
    ax.set_xticklabels([labels[i] for i in x[::step]],
                       color='#94a3b8', fontsize=7, rotation=30, ha='right')
    ax.tick_params(axis='y', colors='#94a3b8', labelsize=7)
    ax.spines[:].set_color('#334155')
    ax.set_title('Rating Evolution', color='#e2e8f0', fontsize=9, pad=6)
    ax.set_ylabel('Rating', color='#94a3b8', fontsize=7)
    fig.tight_layout(pad=0.5)
    return fig


def _build_score_flow_chart(updates, title='Score Flow'):
    """Step chart of score progression during a match."""
    if not updates:
        return None
    fig, ax = plt.subplots(figsize=(8, 2.2), facecolor='#0f172a')
    ax.set_facecolor('#1e293b')
    t1 = [u['team1_score'] for u in updates]
    t2 = [u['team2_score'] for u in updates]
    x = list(range(len(updates)))
    ax.step(x, t1, where='post', color='#3b82f6', linewidth=1.5, label='Team 1')
    ax.step(x, t2, where='post', color='#f59e0b', linewidth=1.5, label='Team 2')
    ax.fill_between(x, t1, t2, where=[a > b for a, b in zip(t1, t2)],
                    alpha=0.12, color='#3b82f6', step='post')
    ax.fill_between(x, t2, t1, where=[b > a for a, b in zip(t1, t2)],
                    alpha=0.12, color='#f59e0b', step='post')
    ax.tick_params(colors='#94a3b8', labelsize=7)
    ax.spines[:].set_color('#334155')
    ax.set_title(title, color='#e2e8f0', fontsize=8, pad=4)
    ax.legend(fontsize=7, facecolor='#1e293b', labelcolor='#e2e8f0',
              edgecolor='#334155', loc='upper left')
    fig.tight_layout(pad=0.4)
    return fig


def _build_practice_bar(sessions, practice_type):
    """Bar chart of practice session hit rates."""
    if not sessions:
        return None
    fig, ax = plt.subplots(figsize=(10, 2.5), facecolor='#0f172a')
    ax.set_facecolor('#1e293b')
    rates = [s.hit_percentage for s in sessions[-20:]]
    dates = [s.started_at.strftime('%b %d') for s in sessions[-20:]]
    x = list(range(len(rates)))
    colours = ['#10b981' if r >= 60 else '#f59e0b' if r >= 40 else '#ef4444' for r in rates]
    ax.bar(x, rates, color=colours, width=0.7, edgecolor='#334155', linewidth=0.3)
    ax.axhline(50, color='#64748b', linewidth=0.7, linestyle='--')
    ax.set_xticks(x)
    ax.set_xticklabels(dates, color='#94a3b8', fontsize=6.5, rotation=40, ha='right')
    ax.tick_params(axis='y', colors='#94a3b8', labelsize=7)
    ax.set_ylim(0, 105)
    ax.set_ylabel('%', color='#94a3b8', fontsize=7)
    ax.spines[:].set_color('#334155')
    ax.set_title(f'{practice_type.capitalize()} Practice — Success Rate per Session',
                 color='#e2e8f0', fontsize=8, pad=4)
    fig.tight_layout(pad=0.4)
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────────────────────
def _parse_ts(ts_str):
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(str(ts_str).replace('Z', '+00:00'))
    except Exception:
        return None


def _fmt_ts(ts_str):
    dt = _parse_ts(ts_str)
    return dt.strftime('%Y-%m-%d %H:%M') if dt else '—'


def _sign(v):
    return f'+{v:.2f}' if v >= 0 else f'{v:.2f}'


def _score_pattern(updates):
    """Classify: dominant / comeback / collapse / close / normal."""
    if not updates or len(updates) < 3:
        return 'insufficient data'
    t1 = [u['team1_score'] for u in updates]
    t2 = [u['team2_score'] for u in updates]
    final_t1, final_t2 = t1[-1], t2[-1]
    winner = 1 if final_t1 > final_t2 else 2
    winner_scores = t1 if winner == 1 else t2
    loser_scores  = t2 if winner == 1 else t1
    margins = [w - l for w, l in zip(winner_scores, loser_scores)]
    avg_margin = sum(margins) / len(margins)
    loser_led = any(l > w for w, l in zip(winner_scores, loser_scores))
    final_margin = abs(final_t1 - final_t2)
    if avg_margin >= 7:
        return 'dominant'
    if loser_led and final_margin <= 4:
        return 'comeback'
    if final_margin <= 2:
        return 'close'
    return 'normal'


def _compute_match_flow(updates, player_side):
    """
    Compute match-flow fields for a single match.
    player_side: 'team1' or 'team2'
    Returns dict with keys: largest_lead, largest_deficit, comeback_win,
    lost_after_leading, close_finish, final_margin.
    """
    if not updates:
        return None
    t1 = [u['team1_score'] for u in updates]
    t2 = [u['team2_score'] for u in updates]
    final_t1, final_t2 = t1[-1], t2[-1]

    if player_side == 'team1':
        my_scores, opp_scores = t1, t2
        player_won = final_t1 > final_t2
    else:
        my_scores, opp_scores = t2, t1
        player_won = final_t2 > final_t1

    diffs = [m - o for m, o in zip(my_scores, opp_scores)]
    largest_lead    = max(diffs) if diffs else 0
    largest_deficit = min(diffs) if diffs else 0
    final_margin    = abs(final_t1 - final_t2)
    close_finish    = final_margin <= 2

    # Comeback win: player was trailing at some point but won
    was_trailing = any(d < 0 for d in diffs[:-1])
    comeback_win = player_won and was_trailing

    # Lost after leading: player was ahead at some point but lost
    was_leading = any(d > 0 for d in diffs[:-1])
    lost_after_leading = (not player_won) and was_leading

    return {
        'largest_lead':      largest_lead,
        'largest_deficit':   largest_deficit,
        'comeback_win':      comeback_win,
        'lost_after_leading':lost_after_leading,
        'close_finish':      close_finish,
        'final_margin':      final_margin,
        'player_won':        player_won,
    }


def _get_player_ranking(player_profile):
    try:
        ids = list(PlayerProfile.objects.filter(
            value__isnull=False
        ).order_by('-value').values_list('id', flat=True))
        rank = ids.index(player_profile.id) + 1
        return rank, len(ids)
    except Exception:
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# Cover page
# ─────────────────────────────────────────────────────────────────────────────
def _cover_page(player, profile, ST, elements):
    generated_at = timezone.now().strftime('%Y-%m-%d %H:%M UTC')
    cover_data = [[
        Paragraph('PFC — AI COACH REPORT v2', ST['cover_title']),
        Paragraph('Performance Dossier for petA UMP AI Coach Analysis', ST['cover_sub']),
        Paragraph(f'Player: {player.name}', ParagraphStyle(
            'cover_player', parent=ST['cover_title'], fontSize=16, spaceAfter=2)),
        Paragraph(f'Rating: {profile.value:.2f}  |  Generated: {generated_at}', ST['cover_sub']),
        Spacer(1, 6),
        Paragraph(
            'This report contains personal playing and training data. '
            'Share it only if you want AI or coaching analysis.',
            ST['cover_disc']
        ),
    ]]
    tbl = Table(cover_data, colWidths=[PAGE_W - 2 * MARGIN])
    tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), C_BG_DARK),
        ('TOPPADDING',    (0, 0), (-1, -1), 20),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 20),
        ('LEFTPADDING',   (0, 0), (-1, -1), 20),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 20),
    ]))
    elements.append(tbl)
    elements.append(Spacer(1, 10))


# ─────────────────────────────────────────────────────────────────────────────
# Section 0 — AI Reader Instructions (verbatim, selectable text)
# ─────────────────────────────────────────────────────────────────────────────
def _section_ai_instructions(ST, elements):
    elements += _section_header('0. INSTRUCTIONS FOR AI READER (petA UMP)', ST)

    paragraphs = [
        ('Purpose of this document',
         'This PDF is a structured performance dossier generated by the PFC (Pétanque Federation Club) '
         'platform. It is intended to be read by an AI coaching assistant (petA UMP) to provide '
         'personalised analysis, feedback, and improvement recommendations to the player.'),

        ('How to read this report',
         'Each section is labelled with a number and a clear title. Data is presented in tables and '
         'key-value grids. Charts are embedded as images. All numerical values use consistent units '
         'and formats described in each section header.'),

        ('Rating system',
         'The PFC uses an Elo-style rating system with a baseline of 100.0. A positive change means '
         'the player won a match against a higher-rated opponent or performed above expectation. '
         'A negative change means the player lost or underperformed relative to opponent rating. '
         'The "Change" column in the rating history table shows the per-match delta.'),

        ('Match history and lineup data',
         'Section 3 shows tournament match history with full lineup information: player names, '
         'roles (pointer/shooter/flex), and match format (tête-à-tête/doublet/triplet). '
         'The "YOU" marker identifies the subject player in the lineup. '
         'Opponent lineup is shown where available from MatchPlayer records.'),

        ('Score progression',
         'Section 4 shows per-match score step charts and match-flow fields. '
         'Section 5 aggregates these across all matches: comeback wins, matches lost after leading, '
         'close finishes (final margin ≤ 2), and largest lead/deficit recorded.'),

        ('Teammate and opponent data',
         'Section 6 shows per-teammate statistics: games played together, W/L record, win rate, '
         'average score differential, total and average rating change, and role combinations. '
         'The "Best Observed Teammate" is the teammate with the highest win rate (minimum 3 games). '
         'Section 7 shows the same analysis for opponents.'),

        ('Practice data',
         'Section 11 shows shooting and pointing practice sessions. '
         'Sessions flagged as invalid (zero shots, no end time, duration < 2 minutes, or '
         'suspiciously short) are listed separately and excluded from statistics. '
         'Only valid sessions contribute to averages and charts.'),

        ('Data quality',
         'Section 12 lists any discrepancies between profile counters and dataset counts, '
         'truncated history, missing score progressions, or missing lineup entries. '
         'The AI reader should treat flagged data points with appropriate uncertainty.'),

        ('Confidentiality',
         'This report contains personal performance data. The player\'s codename is not included '
         'in this document for privacy reasons. Do not share this report without the player\'s consent.'),
    ]

    for heading, body in paragraphs:
        elements.append(Paragraph(heading, ST['instr_head']))
        elements.append(Paragraph(body, ST['instr_body']))

    elements.append(Spacer(1, 6))


# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — Player Identity & Overview
# ─────────────────────────────────────────────────────────────────────────────
def _section_identity(player, profile, ST, elements):
    elements += _section_header('1. PLAYER IDENTITY & OVERVIEW', ST)

    rank, total = _get_player_ranking(profile)
    rank_str = f'#{rank} / {total}' if rank else 'N/A'

    trend_data = profile.get_rating_trend(last_n_matches=10)
    trend_str = (f"{trend_data['trend'].upper()} "
                 f"({_sign(trend_data['change'])} over last {trend_data['matches']} matches)")

    trend_5  = profile.get_rating_trend(last_n_matches=5)
    trend_20 = profile.get_rating_trend(last_n_matches=20)

    level_map = {1: 'Beginner', 2: 'Intermediate', 3: 'Advanced', 4: 'Expert', 5: 'Professional'}
    level_str = level_map.get(profile.skill_level, 'Unknown')

    wr = round(profile.matches_won / profile.matches_played * 100, 1) if profile.matches_played else 0

    pairs = [
        ('Player Name',          player.name),
        ('Player ID',            str(player.id)),
        ('Current Rating',       f'{profile.value:.2f}'),
        ('Global Ranking',       rank_str),
        ('Skill Level',          level_str),
        ('Preferred Position',   (profile.preferred_position or '—').capitalize()),
        ('Matches Played',       str(profile.matches_played)),
        ('Matches Won',          str(profile.matches_won)),
        ('Win Rate',             f'{wr}%'),
        ('Rating vs Baseline',   _sign(profile.value - 100.0)),
        ('Trend (last 5)',        f"{trend_5['trend'].upper()} ({_sign(trend_5['change'])})"),
        ('Trend (last 10)',       f"{trend_data['trend'].upper()} ({_sign(trend_data['change'])})"),
        ('Trend (last 20)',       f"{trend_20['trend'].upper()} ({_sign(trend_20['change'])})"),
    ]
    elements.append(_kv_table(pairs, ST, cols=3))
    elements.append(Spacer(1, 6))


# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — Rating Evolution & Trend Analysis
# ─────────────────────────────────────────────────────────────────────────────
def _section_rating(profile, ST, elements):
    elements += _section_header('2. RATING EVOLUTION & TREND ANALYSIS', ST)

    history = profile.rating_history or []
    if not history:
        elements.append(Paragraph('No rating history available.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    fig = _build_rating_chart(history)
    elements.append(_matplotlib_to_image(fig, width_mm=165))
    elements.append(Spacer(1, 4))

    changes = [e.get('change', 0) for e in history]
    values  = [e.get('new_value', 100.0) for e in history]
    max_val = max(values)
    min_val = min(values)
    variance = float(np.var(changes)) if changes else 0.0
    std_dev  = float(np.std(changes)) if changes else 0.0

    outcomes = ['W' if e.get('change', 0) > 0 else 'L' for e in history]
    best_win_streak = cur = 0
    for o in outcomes:
        cur = cur + 1 if o == 'W' else 0
        best_win_streak = max(best_win_streak, cur)

    pairs = [
        ('Total History Entries', str(len(history))),
        ('Peak Rating',           f'{max_val:.2f}'),
        ('Lowest Rating',         f'{min_val:.2f}'),
        ('Current vs Peak',       _sign(profile.value - max_val)),
        ('Change Variance',       f'{variance:.3f}'),
        ('Change Std Dev',        f'{std_dev:.3f}'),
        ('Best Win Streak',       str(best_win_streak)),
        ('Avg Change / Match',    f'{sum(changes)/len(changes):.3f}' if changes else '—'),
        ('Largest Single Gain',   f'+{max(changes):.2f}' if changes else '—'),
        ('Largest Single Loss',   f'{min(changes):.2f}' if changes else '—'),
    ]
    elements.append(_kv_table(pairs, ST, cols=3))

    elements.append(Spacer(1, 4))
    elements.append(Paragraph('Full Rating History (most recent 30 entries)', ST['label']))
    headers = ['#', 'Date', 'Old', 'New', 'Change', 'Opp Rating', 'Score', 'Type']
    rows = []
    for i, e in enumerate(history[-30:], max(1, len(history) - 29)):
        rows.append([
            str(i),
            _fmt_ts(e.get('timestamp', '')),
            f"{e.get('old_value', 0):.2f}",
            f"{e.get('new_value', 0):.2f}",
            _sign(e.get('change', 0)),
            f"{e.get('opponent_value', 0):.2f}",
            f"{e.get('own_score', '?')}-{e.get('opponent_score', '?')}",
            e.get('match_type', '—'),
        ])
    cw = [14*mm, 30*mm, 22*mm, 22*mm, 22*mm, 26*mm, 20*mm, 20*mm]
    elements.append(_data_table(headers, rows, ST, col_widths=cw))
    elements.append(Spacer(1, 6))


# ─────────────────────────────────────────────────────────────────────────────
# Section 3 — Tournament Match History (with full lineup)
# ─────────────────────────────────────────────────────────────────────────────
def _section_match_history(player, tournament_matches, lineup_map, ST, elements):
    elements += _section_header('3. TOURNAMENT MATCH HISTORY (with lineup)', ST)

    if not tournament_matches:
        elements.append(Paragraph('No tournament match history available.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    for m in tournament_matches[:30]:
        result = 'WIN' if getattr(m, 'player_won', False) else 'LOSS'
        score  = f"{getattr(m, 'player_score', '?')}-{getattr(m, 'opponent_score', '?')}"
        dur    = '—'
        if m.duration:
            total_s = int(m.duration.total_seconds())
            dur = f"{total_s // 60}m {total_s % 60}s"
        date_str = m.end_time.strftime('%Y-%m-%d') if m.end_time else '—'
        t_name   = m.tournament.name[:20] if m.tournament else '—'
        r_name   = m.round.name if m.round else '—'
        fmt      = (m.match_type or '—').replace('_', ' ')

        # Lineup for this match
        match_lineup = lineup_map.get(m.id, {})
        my_side  = 'team1' if getattr(m, 'player_team', None) == m.team1 else 'team2'
        opp_side = 'team2' if my_side == 'team1' else 'team1'

        def _fmt_lineup(side):
            players = match_lineup.get(side, [])
            if not players:
                return '—'
            parts = []
            for mp in players:
                name = mp.player.name if mp.player else '?'
                role = (mp.role or 'flex')[:3].upper()
                you  = ' [YOU]' if mp.player_id == player.id else ''
                parts.append(f'{name} ({role}){you}')
            return ', '.join(parts)

        my_lineup  = _fmt_lineup(my_side)
        opp_lineup = _fmt_lineup(opp_side)

        block = [
            [Paragraph(f'{date_str}  |  {t_name}  |  Round: {r_name}  |  Format: {fmt}  |  Score: {score}  |  {result}  |  Duration: {dur}', ST['body_bold'])],
            [Paragraph(f'Your side:  {my_lineup}', ST['body'])],
            [Paragraph(f'Opponents:  {opp_lineup}', ST['body'])],
        ]
        tbl = Table(block, colWidths=[PAGE_W - 2 * MARGIN])
        tbl.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (0, 0), C_BG_LIGHT),
            ('TOPPADDING',    (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING',   (0, 0), (-1, -1), 6),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
            ('LINEBELOW',     (0, -1), (-1, -1), 0.5, C_BORDER),
        ]))
        elements.append(tbl)

    elements.append(Spacer(1, 6))


# ─────────────────────────────────────────────────────────────────────────────
# Section 4 — Score Progression Analysis
# ─────────────────────────────────────────────────────────────────────────────
def _section_score_progression(player, tournament_matches, ST, elements):
    elements += _section_header('4. SCORE PROGRESSION ANALYSIS (ScoreUpdate Log)', ST)

    from matches.models import LiveScoreboard, ScoreUpdate

    scored_matches = []
    for m in tournament_matches[:20]:
        # Use the correct field name: tournament_match (not the generic 'match')
        sb = LiveScoreboard.objects.filter(tournament_match=m).first()
        if sb:
            updates = list(
                ScoreUpdate.objects.filter(scoreboard=sb)
                .order_by('timestamp')
                .values('team1_score', 'team2_score', 'update_type', 'timestamp')
            )
            if updates:
                scored_matches.append((m, updates))

    if not scored_matches:
        elements.append(Paragraph('No score progression data available for recent matches.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    elements.append(Paragraph(
        f'Score progression data found for {len(scored_matches)} of {len(tournament_matches[:20])} recent matches.',
        ST['body']
    ))
    elements.append(Spacer(1, 4))

    for m, updates in scored_matches[:6]:
        my_side  = 'team1' if getattr(m, 'player_team', None) == m.team1 else 'team2'
        pattern  = _score_pattern(updates)
        flow     = _compute_match_flow(updates, my_side)
        date_str = m.end_time.strftime('%Y-%m-%d') if m.end_time else '—'
        opp      = getattr(m, 'opponent_name', '—')
        final    = f"{updates[-1]['team1_score']}-{updates[-1]['team2_score']}"
        title    = f"{date_str}  vs {opp}  [{final}]  Pattern: {pattern.upper()}"

        fig = _build_score_flow_chart(updates, title=title)
        if fig:
            elements.append(_matplotlib_to_image(fig, width_mm=155))
            elements.append(Spacer(1, 3))

        if flow:
            flow_pairs = [
                ('Largest Lead',       str(flow['largest_lead'])),
                ('Largest Deficit',    str(flow['largest_deficit'])),
                ('Comeback Win',       'YES' if flow['comeback_win'] else 'no'),
                ('Lost After Leading', 'YES' if flow['lost_after_leading'] else 'no'),
                ('Close Finish (≤2)',  'YES' if flow['close_finish'] else 'no'),
                ('Final Margin',       str(flow['final_margin'])),
            ]
            elements.append(_kv_table(flow_pairs, ST, cols=3))

        notable = [u for u in updates if u['update_type'] != 'increment']
        if notable:
            headers = ['Timestamp', 'T1', 'T2', 'Type']
            rows = [[
                _fmt_ts(str(u['timestamp'])),
                str(u['team1_score']),
                str(u['team2_score']),
                u['update_type'],
            ] for u in notable[:10]]
            cw = [50*mm, 20*mm, 20*mm, 30*mm]
            elements.append(_data_table(headers, rows, ST, col_widths=cw))
        elements.append(Spacer(1, 5))


# ─────────────────────────────────────────────────────────────────────────────
# Section 5 — Match-Flow Aggregate
# ─────────────────────────────────────────────────────────────────────────────
def _section_match_flow_aggregate(player, tournament_matches, ST, elements):
    elements += _section_header('5. MATCH-FLOW AGGREGATE', ST)

    from matches.models import LiveScoreboard, ScoreUpdate

    total_with_data = 0
    comeback_wins   = 0
    lost_after_lead = 0
    close_wins      = 0
    close_losses    = 0
    major_comebacks = 0   # deficit ≥ 5 at some point, still won
    max_lead_ever   = 0
    max_deficit_ever= 0

    for m in tournament_matches:
        # Use the correct field name: tournament_match (not the generic 'match')
        sb = LiveScoreboard.objects.filter(tournament_match=m).first()
        if not sb:
            continue
        updates = list(
            ScoreUpdate.objects.filter(scoreboard=sb)
            .order_by('timestamp')
            .values('team1_score', 'team2_score', 'update_type', 'timestamp')
        )
        if not updates:
            continue
        my_side = 'team1' if getattr(m, 'player_team', None) == m.team1 else 'team2'
        flow = _compute_match_flow(updates, my_side)
        if not flow:
            continue
        total_with_data += 1
        if flow['comeback_win']:
            comeback_wins += 1
            if flow['largest_deficit'] <= -5:
                major_comebacks += 1
        if flow['lost_after_leading']:
            lost_after_lead += 1
        if flow['close_finish']:
            if flow['player_won']:
                close_wins += 1
            else:
                close_losses += 1
        max_lead_ever    = max(max_lead_ever,    flow['largest_lead'])
        max_deficit_ever = min(max_deficit_ever, flow['largest_deficit'])

    if total_with_data == 0:
        elements.append(Paragraph('No score progression data available for aggregate analysis.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    pairs = [
        ('Matches with Score Data',   str(total_with_data)),
        ('Comeback Wins',             str(comeback_wins)),
        ('Major Comebacks (deficit≥5)',str(major_comebacks)),
        ('Lost After Leading',        str(lost_after_lead)),
        ('Close Wins (margin≤2)',     str(close_wins)),
        ('Close Losses (margin≤2)',   str(close_losses)),
        ('Largest Lead Recorded',     str(max_lead_ever)),
        ('Largest Deficit Recorded',  str(max_deficit_ever)),
        ('Close Game W/L',            f'{close_wins}W / {close_losses}L'),
    ]
    elements.append(_kv_table(pairs, ST, cols=3))
    elements.append(Spacer(1, 6))


# ─────────────────────────────────────────────────────────────────────────────
# Section 6 — Teammate Statistics
# ─────────────────────────────────────────────────────────────────────────────
def _section_teammate_stats(player, tournament_matches, lineup_map, ST, elements):
    elements += _section_header('6. TEAMMATE STATISTICS', ST)

    if not tournament_matches:
        elements.append(Paragraph('No tournament match data available.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    # Accumulate per-teammate stats
    tm_stats = defaultdict(lambda: {
        'games': 0, 'wins': 0,
        'score_diff_total': 0,
        'rating_change_total': 0.0,
        'roles': defaultdict(int),
        'player_obj': None,
    })

    history = getattr(player, 'profile', None)
    history_list = (history.rating_history or []) if history else []

    for m in tournament_matches:
        my_side  = 'team1' if getattr(m, 'player_team', None) == m.team1 else 'team2'
        match_lineup = lineup_map.get(m.id, {})
        teammates = [mp for mp in match_lineup.get(my_side, [])
                     if mp.player_id != player.id]

        won = getattr(m, 'player_won', False)
        p_score = getattr(m, 'player_score', 0) or 0
        o_score = getattr(m, 'opponent_score', 0) or 0
        diff = p_score - o_score

        # Find rating change for this match from history
        rating_change = 0.0
        if m.end_time:
            for entry in history_list:
                ts = _parse_ts(entry.get('timestamp', ''))
                if ts and abs((ts - m.end_time.replace(tzinfo=dt_timezone.utc)).total_seconds()) < 3600:
                    rating_change = entry.get('change', 0.0)
                    break

        for mp in teammates:
            name = mp.player.name if mp.player else f'Player#{mp.player_id}'
            tm_stats[name]['games'] += 1
            if won:
                tm_stats[name]['wins'] += 1
            tm_stats[name]['score_diff_total'] += diff
            tm_stats[name]['rating_change_total'] += rating_change
            role = mp.role or 'flex'
            tm_stats[name]['roles'][role] += 1
            if mp.player:
                tm_stats[name]['player_obj'] = mp.player

    if not tm_stats:
        elements.append(Paragraph('No teammate data found in lineup records.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    headers = ['Teammate', 'Games', 'W', 'L', 'Win%', 'Avg Score Diff', 'Total ΔRating', 'Avg ΔRating', 'Roles']
    rows = []
    best_name, best_wr = None, -1.0
    for name, s in sorted(tm_stats.items(), key=lambda x: -x[1]['games']):
        g = s['games']
        w = s['wins']
        wr = round(w / g * 100, 1) if g else 0
        avg_diff = round(s['score_diff_total'] / g, 1) if g else 0
        total_rc = round(s['rating_change_total'], 2)
        avg_rc   = round(s['rating_change_total'] / g, 3) if g else 0
        roles_str = ', '.join(f'{r}×{c}' for r, c in sorted(s['roles'].items(), key=lambda x: -x[1]))
        rows.append([name[:22], str(g), str(w), str(g-w), f'{wr}%',
                     str(avg_diff), _sign(total_rc), _sign(avg_rc), roles_str[:20]])
        if g >= 3 and wr > best_wr:
            best_wr, best_name = wr, name

    cw = [38*mm, 14*mm, 10*mm, 10*mm, 14*mm, 22*mm, 22*mm, 22*mm, 24*mm]
    elements.append(_data_table(headers, rows, ST, col_widths=cw))

    if best_name:
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(
            f'Best Observed Teammate (min 3 games): {best_name} — Win Rate {best_wr:.1f}%',
            ST['body_bold']
        ))
    elements.append(Spacer(1, 6))


# ─────────────────────────────────────────────────────────────────────────────
# Section 7 — Opponent Statistics
# ─────────────────────────────────────────────────────────────────────────────
def _section_opponent_stats(player, tournament_matches, lineup_map, ST, elements):
    elements += _section_header('7. OPPONENT STATISTICS', ST)

    if not tournament_matches:
        elements.append(Paragraph('No tournament match data available.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    opp_stats = defaultdict(lambda: {
        'games': 0, 'wins': 0,
        'score_diff_total': 0,
    })

    for m in tournament_matches:
        my_side  = 'team1' if getattr(m, 'player_team', None) == m.team1 else 'team2'
        opp_side = 'team2' if my_side == 'team1' else 'team1'
        match_lineup = lineup_map.get(m.id, {})
        opponents = match_lineup.get(opp_side, [])

        won = getattr(m, 'player_won', False)
        p_score = getattr(m, 'player_score', 0) or 0
        o_score = getattr(m, 'opponent_score', 0) or 0
        diff = p_score - o_score

        if opponents:
            for mp in opponents:
                name = mp.player.name if mp.player else f'Player#{mp.player_id}'
                opp_stats[name]['games'] += 1
                if won:
                    opp_stats[name]['wins'] += 1
                opp_stats[name]['score_diff_total'] += diff
        else:
            # Fall back to team name
            opp_team = m.team2 if my_side == 'team1' else m.team1
            name = opp_team.name if opp_team else '—'
            opp_stats[name]['games'] += 1
            if won:
                opp_stats[name]['wins'] += 1
            opp_stats[name]['score_diff_total'] += diff

    if not opp_stats:
        elements.append(Paragraph('No opponent data available.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    headers = ['Opponent', 'Games', 'W', 'L', 'Win%', 'Avg Score Diff']
    rows = []
    for name, s in sorted(opp_stats.items(), key=lambda x: -x[1]['games']):
        g = s['games']
        w = s['wins']
        wr = round(w / g * 100, 1) if g else 0
        avg_diff = round(s['score_diff_total'] / g, 1) if g else 0
        rows.append([name[:28], str(g), str(w), str(g-w), f'{wr}%', str(avg_diff)])

    cw = [50*mm, 16*mm, 12*mm, 12*mm, 18*mm, 28*mm]
    elements.append(_data_table(headers, rows, ST, col_widths=cw))
    elements.append(Spacer(1, 6))


# ─────────────────────────────────────────────────────────────────────────────
# Section 8 — Role & Format Breakdown
# ─────────────────────────────────────────────────────────────────────────────
def _section_role_format(player, profile, ST, elements):
    elements += _section_header('8. ROLE & FORMAT BREAKDOWN', ST)

    role_dist   = profile.get_role_distribution()
    format_stats = profile.get_format_stats()

    if role_dist:
        elements.append(Paragraph('Role Distribution (from MatchPlayer records)', ST['label']))
        headers = ['Role', 'Count', 'Percentage']
        rows = [[r, str(d['count']), f"{d['percentage']}%"]
                for r, d in sorted(role_dist.items(), key=lambda x: -x[1]['count'])]
        cw = [60*mm, 40*mm, 40*mm]
        elements.append(_data_table(headers, rows, ST, col_widths=cw))
        elements.append(Spacer(1, 4))

    if format_stats:
        elements.append(Paragraph('Format Statistics (from match participation records)', ST['label']))
        headers = ['Format', 'Played', 'Won', 'Win%']
        rows = [[fmt.replace('_', ' ').title(),
                 str(s['matches_played']),
                 str(s['matches_won']),
                 f"{s['win_rate']}%"]
                for fmt, s in sorted(format_stats.items(), key=lambda x: -x[1]['matches_played'])]
        cw = [60*mm, 30*mm, 30*mm, 30*mm]
        elements.append(_data_table(headers, rows, ST, col_widths=cw))

    if not role_dist and not format_stats:
        elements.append(Paragraph('No role or format data available.', ST['body']))

    elements.append(Spacer(1, 6))


# ─────────────────────────────────────────────────────────────────────────────
# Section 9 — Tournament Breakdown
# ─────────────────────────────────────────────────────────────────────────────
def _section_tournament_breakdown(player, tournament_matches, ST, elements):
    elements += _section_header('9. TOURNAMENT BREAKDOWN', ST)

    if not tournament_matches:
        elements.append(Paragraph('No tournament data available.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    by_tournament = defaultdict(list)
    for m in tournament_matches:
        t_name = m.tournament.name if m.tournament else 'Unknown'
        by_tournament[t_name].append(m)

    headers = ['Tournament', 'Played', 'Won', 'Lost', 'Win%', 'Avg Scored', 'Avg Conceded']
    rows = []
    for t_name, matches in sorted(by_tournament.items()):
        played  = len(matches)
        won     = sum(1 for m in matches if getattr(m, 'player_won', False))
        wr      = round(won / played * 100, 1) if played else 0
        scores  = [getattr(m, 'player_score', 0) or 0 for m in matches]
        conceded= [getattr(m, 'opponent_score', 0) or 0 for m in matches]
        avg_s   = round(sum(scores) / len(scores), 1) if scores else 0
        avg_c   = round(sum(conceded) / len(conceded), 1) if conceded else 0
        rows.append([t_name[:30], str(played), str(won), str(played - won),
                     f'{wr}%', str(avg_s), str(avg_c)])
    cw = [55*mm, 16*mm, 14*mm, 14*mm, 18*mm, 22*mm, 22*mm]
    elements.append(_data_table(headers, rows, ST, col_widths=cw))
    elements.append(Spacer(1, 6))


# ─────────────────────────────────────────────────────────────────────────────
# Section 10 — Friendly Game Breakdown
# ─────────────────────────────────────────────────────────────────────────────
def _section_friendly_games(player, friendly_matches, ST, elements):
    elements += _section_header('10. FRIENDLY GAME BREAKDOWN', ST)

    if not friendly_matches:
        elements.append(Paragraph('No friendly game history available.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    total = len(friendly_matches)
    wins  = sum(1 for m in friendly_matches if m.get('won'))
    wr    = round(wins / total * 100, 1) if total else 0

    pairs = [
        ('Total Friendly Games', str(total)),
        ('Wins',                 str(wins)),
        ('Losses',               str(total - wins)),
        ('Win Rate',             f'{wr}%'),
    ]
    elements.append(_kv_table(pairs, ST, cols=4))
    elements.append(Spacer(1, 4))

    headers = ['Date', 'Game', 'Team', 'Position', 'Black', 'White', 'Result']
    rows = []
    for m in friendly_matches[:25]:
        date_str = m['date'].strftime('%Y-%m-%d') if m.get('date') else '—'
        rows.append([
            date_str,
            str(m.get('game_name', '—'))[:20],
            str(m.get('team', '—')),
            str(m.get('position', '—')),
            str(m.get('black_score', '?')),
            str(m.get('white_score', '?')),
            'WIN' if m.get('won') else 'LOSS',
        ])
    cw = [24*mm, 40*mm, 20*mm, 22*mm, 16*mm, 16*mm, 16*mm]
    elements.append(_data_table(headers, rows, ST, col_widths=cw))
    elements.append(Spacer(1, 4))

    # ── Friendly game score progression (reuses existing ScoreUpdate log) ──
    from matches.models import LiveScoreboard, ScoreUpdate
    elements += _section_header('10b. FRIENDLY GAME SCORE PROGRESSION', ST)

    scored_friendly = []
    for m in friendly_matches[:20]:
        game_id = m.get('game_id')
        if not game_id:
            continue
        # Use the correct field name: friendly_game
        sb = LiveScoreboard.objects.filter(friendly_game_id=game_id).first()
        if sb:
            updates = list(
                ScoreUpdate.objects.filter(scoreboard=sb)
                .order_by('timestamp')
                .values('team1_score', 'team2_score', 'update_type', 'timestamp')
            )
            if updates:
                scored_friendly.append((m, updates))

    if not scored_friendly:
        elements.append(Paragraph('No score progression data available for recent friendly games.', ST['body']))
        elements.append(Spacer(1, 6))
    else:
        elements.append(Paragraph(
            f'Score progression data found for {len(scored_friendly)} of {min(20, len(friendly_matches))} recent friendly games.',
            ST['body']
        ))
        elements.append(Spacer(1, 4))

        for m, updates in scored_friendly[:6]:
            # Determine player side: 'team1' = BLACK, 'team2' = WHITE
            my_side  = 'team1' if str(m.get('team', '')).upper() == 'BLACK' else 'team2'
            pattern  = _score_pattern(updates)
            flow     = _compute_match_flow(updates, my_side)
            date_str = m['date'].strftime('%Y-%m-%d') if m.get('date') else '—'
            final    = f"{updates[-1]['team1_score']}-{updates[-1]['team2_score']}"
            title    = f"{date_str}  {m.get('game_name', 'Friendly Game')}  [{final}]  Pattern: {pattern.upper()}"

            fig = _build_score_flow_chart(updates, title=title)
            if fig:
                elements.append(_matplotlib_to_image(fig, width_mm=155))
                elements.append(Spacer(1, 3))

            if flow:
                flow_pairs = [
                    ('Largest Lead',       str(flow['largest_lead'])),
                    ('Largest Deficit',    str(flow['largest_deficit'])),
                    ('Comeback Win',       'YES' if flow['comeback_win'] else 'no'),
                    ('Lost After Leading', 'YES' if flow['lost_after_leading'] else 'no'),
                    ('Close Finish (≤2)',  'YES' if flow['close_finish'] else 'no'),
                    ('Final Margin',       str(flow['final_margin'])),
                ]
                elements.append(_kv_table(flow_pairs, ST, cols=3))

            notable = [u for u in updates if u['update_type'] != 'increment']
            if notable:
                headers_n = ['Timestamp', 'T1', 'T2', 'Type']
                rows_n = [[
                    _fmt_ts(str(u['timestamp'])),
                    str(u['team1_score']),
                    str(u['team2_score']),
                    u['update_type'],
                ] for u in notable[:10]]
                cw_n = [50*mm, 20*mm, 20*mm, 30*mm]
                elements.append(_data_table(headers_n, rows_n, ST, col_widths=cw_n))
            elements.append(Spacer(1, 5))


# ─────────────────────────────────────────────────────────────────────────────
# Section 11 — Practice Data
# ─────────────────────────────────────────────────────────────────────────────
def _section_practice(player, ST, elements):
    elements += _section_header('11. PRACTICE DATA', ST)

    from practice.models import PracticeSession
    from friendly_games.models import PlayerCodename

    codename = None
    try:
        pc = PlayerCodename.objects.filter(player=player).first()
        if pc:
            codename = pc.codename
    except Exception:
        pass

    if not codename:
        elements.append(Paragraph('No codename linked — practice data unavailable.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    all_sessions = list(PracticeSession.objects.filter(
        player_codename=codename
    ).order_by('-started_at')[:60])

    if not all_sessions:
        elements.append(Paragraph('No practice sessions recorded for this player.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    # Validate sessions
    valid_sessions  = []
    flagged_sessions = []
    for s in all_sessions:
        flags = []
        if s.total_shots == 0:
            flags.append('zero shots')
        if not s.ended_at:
            flags.append('no end time')
        elif s.ended_at and s.started_at:
            dur_s = (s.ended_at - s.started_at).total_seconds()
            if dur_s < 120:
                flags.append(f'duration only {int(dur_s)}s')
        if flags:
            flagged_sessions.append((s, flags))
        else:
            valid_sessions.append(s)

    shooting_sessions = [s for s in valid_sessions if s.practice_type == 'shooting']
    pointing_sessions = [s for s in valid_sessions if s.practice_type == 'pointing']

    pairs = []
    for ptype, sess_list in [('Shooting', shooting_sessions), ('Pointing', pointing_sessions)]:
        if sess_list:
            avg_rate  = round(sum(s.hit_percentage for s in sess_list) / len(sess_list), 1)
            best_rate = round(max(s.hit_percentage for s in sess_list), 1)
            pairs += [
                (f'{ptype} Valid Sessions', str(len(sess_list))),
                (f'{ptype} Avg Success%',   f'{avg_rate}%'),
                (f'{ptype} Best Session',   f'{best_rate}%'),
            ]

    pairs += [
        ('Total Sessions',   str(len(all_sessions))),
        ('Valid Sessions',   str(len(valid_sessions))),
        ('Flagged/Excluded', str(len(flagged_sessions))),
    ]
    elements.append(_kv_table(pairs, ST, cols=3))
    elements.append(Spacer(1, 4))

    if shooting_sessions:
        fig = _build_practice_bar(shooting_sessions, 'shooting')
        if fig:
            elements.append(_matplotlib_to_image(fig, width_mm=165))
            elements.append(Spacer(1, 3))

    if pointing_sessions:
        fig = _build_practice_bar(pointing_sessions, 'pointing')
        if fig:
            elements.append(_matplotlib_to_image(fig, width_mm=165))
            elements.append(Spacer(1, 3))

    elements.append(Paragraph('Valid Practice Sessions (last 20)', ST['label']))
    headers = ['Date', 'Type', 'Dist', 'Shots', 'Success%', 'Carreaux%', 'Miss%', 'Duration']
    rows = []
    for s in valid_sessions[:20]:
        dur = '—'
        if s.ended_at:
            secs = int((s.ended_at - s.started_at).total_seconds())
            dur = f'{secs // 60}m'
        rows.append([
            s.started_at.strftime('%Y-%m-%d'),
            s.practice_type.capitalize(),
            s.distance,
            str(s.total_shots),
            f'{s.hit_percentage:.1f}%',
            f'{s.carreau_percentage:.1f}%' if s.practice_type == 'shooting' else '—',
            f'{s.miss_percentage:.1f}%' if s.practice_type == 'shooting' else '—',
            dur,
        ])
    cw = [26*mm, 22*mm, 16*mm, 16*mm, 22*mm, 22*mm, 18*mm, 18*mm]
    elements.append(_data_table(headers, rows, ST, col_widths=cw))

    if flagged_sessions:
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(
            f'Flagged / Excluded Sessions ({len(flagged_sessions)} total — not included in statistics)',
            ST['label']
        ))
        headers2 = ['Date', 'Type', 'Shots', 'Flags']
        rows2 = []
        for s, flags in flagged_sessions[:10]:
            rows2.append([
                s.started_at.strftime('%Y-%m-%d'),
                s.practice_type.capitalize(),
                str(s.total_shots),
                ', '.join(flags),
            ])
        cw2 = [26*mm, 22*mm, 16*mm, 92*mm]
        elements.append(_data_table(headers2, rows2, ST, col_widths=cw2))

    elements.append(Spacer(1, 6))


# ─────────────────────────────────────────────────────────────────────────────
# Section 12 — Data Quality Notes
# ─────────────────────────────────────────────────────────────────────────────
def _section_data_quality(player, profile, tournament_matches, lineup_map, ST, elements):
    elements += _section_header('12. DATA QUALITY NOTES', ST)

    notes = []

    # Profile counter vs dataset discrepancy
    dataset_played = len(tournament_matches)
    if profile.matches_played != dataset_played:
        notes.append(
            f'Profile counter: matches_played={profile.matches_played}, '
            f'but dataset contains {dataset_played} completed tournament matches. '
            f'Difference: {abs(profile.matches_played - dataset_played)}. '
            f'This may be due to matches played before profile tracking began, '
            f'or matches not yet reflected in the counter.'
        )

    # Rating history truncation
    history = profile.rating_history or []
    if len(history) < profile.matches_played:
        notes.append(
            f'Rating history has {len(history)} entries but profile shows '
            f'{profile.matches_played} matches played. '
            f'{profile.matches_played - len(history)} match(es) may be missing from history.'
        )

    # Missing score progressions
    from matches.models import LiveScoreboard
    matches_with_sb = 0
    for m in tournament_matches[:20]:
        # Use the correct field name: tournament_match (not the generic 'match')
        if LiveScoreboard.objects.filter(tournament_match=m).exists():
            matches_with_sb += 1
    if tournament_matches and matches_with_sb < len(tournament_matches[:20]):
        notes.append(
            f'Score progression data available for {matches_with_sb} of '
            f'{min(20, len(tournament_matches))} recent matches. '
            f'{min(20, len(tournament_matches)) - matches_with_sb} match(es) have no ScoreUpdate log.'
        )

    # Missing lineup entries
    matches_with_lineup = sum(1 for m in tournament_matches if lineup_map.get(m.id))
    if tournament_matches and matches_with_lineup < len(tournament_matches):
        notes.append(
            f'Lineup data (MatchPlayer records) available for {matches_with_lineup} of '
            f'{len(tournament_matches)} matches. '
            f'{len(tournament_matches) - matches_with_lineup} match(es) have no lineup records.'
        )

    if not notes:
        elements.append(Paragraph('No data quality issues detected.', ST['body']))
    else:
        for i, note in enumerate(notes, 1):
            elements.append(Paragraph(f'[DQ{i}] {note}', ST['body']))
            elements.append(Spacer(1, 3))

    elements.append(Spacer(1, 6))


# ─────────────────────────────────────────────────────────────────────────────
# Main view
# ─────────────────────────────────────────────────────────────────────────────
def ai_coach_report(request, player_id):
    """
    Generate and stream the AI Coach Report PDF (v2) for a player.
    Access: own profile (session match), legacy player_id session, or staff.
    """
    player = get_object_or_404(
        Player.objects.select_related('profile', 'team'),
        id=player_id
    )

    # Access control
    is_own = False

    # 1. Staff / superuser
    if hasattr(request, 'user') and request.user.is_authenticated and request.user.is_staff:
        is_own = True

    # 2. Codename-based session (primary login)
    if not is_own:
        session_codename = request.session.get('player_codename')
        if session_codename and request.session.get('session_active'):
            try:
                from friendly_games.models import PlayerCodename as _PC
                _pc = _PC.objects.get(codename=session_codename.upper())
                is_own = (_pc.player_id == player.id)
            except Exception:
                pass

    # 3. Legacy player_id session
    if not is_own:
        session_player_id = request.session.get('player_id')
        if session_player_id and int(session_player_id) == player.id:
            is_own = True

    if not is_own:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("You do not have permission to access this player's AI Coach Report.")

    profile = getattr(player, 'profile', None)
    if profile is None:
        raise Http404("Player profile not found.")

    # ── Gather tournament matches ─────────────────────────────────────────────
    from django.db.models import Q
    from matches.models import Match, MatchPlayer

    try:
        from matches.models_participant import TeamMatchParticipant
        participated_ids = TeamMatchParticipant.objects.filter(
            player=player, played=True
        ).values_list('match_id', flat=True)
        tournament_matches = list(
            Match.objects.filter(id__in=participated_ids, status='completed')
            .select_related('team1', 'team2', 'tournament', 'round', 'court')
            .order_by('-end_time')[:50]
        )
    except ImportError:
        tournament_matches = list(
            Match.objects.filter(
                Q(team1=player.team) | Q(team2=player.team),
                status='completed'
            ).select_related('team1', 'team2', 'tournament', 'round', 'court')
            .order_by('-end_time')[:50]
        )

    # Annotate player_team, player_won, scores, opponent_name
    try:
        mp_map = {
            mp.match_id: mp.team
            for mp in MatchPlayer.objects.filter(
                match__in=tournament_matches, player=player
            ).select_related('team')
        }
    except Exception:
        mp_map = {}

    for m in tournament_matches:
        actual_team = mp_map.get(m.id) or player.team
        if actual_team == m.team1:
            p_score = m.team1_score or 0
            o_score = m.team2_score or 0
            opp_name = m.team2.name if m.team2 else '—'
        else:
            p_score = m.team2_score or 0
            o_score = m.team1_score or 0
            opp_name = m.team1.name if m.team1 else '—'
        m.player_team    = actual_team
        m.player_score   = p_score
        m.opponent_score = o_score
        m.opponent_name  = opp_name
        m.player_won     = p_score > o_score

    # Build lineup_map: {match_id: {'team1': [MatchPlayer, ...], 'team2': [...]}}
    lineup_map = defaultdict(lambda: {'team1': [], 'team2': []})
    try:
        all_mps = MatchPlayer.objects.filter(
            match__in=tournament_matches
        ).select_related('player', 'team', 'match')
        for mp in all_mps:
            m = mp.match
            if mp.team == m.team1:
                lineup_map[m.id]['team1'].append(mp)
            elif mp.team == m.team2:
                lineup_map[m.id]['team2'].append(mp)
    except Exception:
        pass

    # ── Gather friendly matches ───────────────────────────────────────────────
    friendly_matches = []
    try:
        from friendly_games.models import FriendlyGamePlayer
        for fgp in FriendlyGamePlayer.objects.filter(
            player=player, codename_verified=True, game__status='COMPLETED'
        ).select_related('game').order_by('-game__created_at')[:40]:
            g = fgp.game
            friendly_matches.append({
                'date':        g.created_at,
                'game_name':   g.name,
                'team':        fgp.team,
                'position':    fgp.position,
                'black_score': g.black_team_score,
                'white_score': g.white_team_score,
                'won':         fgp.games_won > 0,
                'game_id':     g.id,
            })
    except Exception:
        pass

    # ── Build PDF ─────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN,  bottomMargin=MARGIN,
        title=f'PFC AI Coach Report v2 — {player.name}',
        author='PFC Platform',
        subject='AI Coach Performance Dossier v2',
    )

    ST = _styles()
    elements = []

    _cover_page(player, profile, ST, elements)
    elements.append(PageBreak())

    _section_ai_instructions(ST, elements)
    elements.append(PageBreak())

    _section_identity(player, profile, ST, elements)
    _section_rating(profile, ST, elements)
    elements.append(PageBreak())

    _section_match_history(player, tournament_matches, lineup_map, ST, elements)
    elements.append(PageBreak())

    _section_score_progression(player, tournament_matches, ST, elements)
    _section_match_flow_aggregate(player, tournament_matches, ST, elements)
    elements.append(PageBreak())

    _section_teammate_stats(player, tournament_matches, lineup_map, ST, elements)
    _section_opponent_stats(player, tournament_matches, lineup_map, ST, elements)
    elements.append(PageBreak())

    _section_role_format(player, profile, ST, elements)
    _section_tournament_breakdown(player, tournament_matches, ST, elements)
    elements.append(PageBreak())

    _section_friendly_games(player, friendly_matches, ST, elements)
    elements.append(PageBreak())

    _section_practice(player, ST, elements)
    elements.append(PageBreak())

    _section_data_quality(player, profile, tournament_matches, lineup_map, ST, elements)

    doc.build(elements)
    buf.seek(0)

    filename = (f'PFC_AICoachReport_v2_{player.name.replace(" ", "_")}'
                f'_{timezone.now().strftime("%Y%m%d")}.pdf')
    response = HttpResponse(buf.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
