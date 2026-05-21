"""
AI Coach Report Generator
=========================
Generates a dense structured PDF performance dossier for a PFC player.
Optimized for AI readability (petA UMP) and human coaching analysis.

Accessible via: /teams/players/<player_id>/ai-coach-report/
Only the player themselves (session match) or staff can download.
"""

import io
import json
import math
from collections import defaultdict
from datetime import datetime, timezone as dt_timezone

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server use
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image, KeepTogether, PageBreak
)
from reportlab.platypus.flowables import Flowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

from .models import Player, PlayerProfile

# ─────────────────────────────────────────────────────────────────────────────
# Colour palette (dark, data-dense aesthetic)
# ─────────────────────────────────────────────────────────────────────────────
C_BG_DARK   = colors.HexColor('#0f172a')   # page header background
C_BG_MID    = colors.HexColor('#1e293b')   # section header background
C_BG_LIGHT  = colors.HexColor('#f1f5f9')   # alternating row tint
C_ACCENT    = colors.HexColor('#3b82f6')   # blue accent
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
        'caption':     s('caption', fontSize=7.5, textColor=colors.HexColor('#64748b'),
                         fontName='Helvetica-Oblique', alignment=TA_CENTER, spaceAfter=2),
        'th':          s('th', fontSize=8, textColor=C_TEXT_LIGHT,
                         fontName='Helvetica-Bold', alignment=TA_CENTER),
        'td':          s('td', fontSize=8, textColor=C_TEXT_DARK,
                         fontName='Helvetica', alignment=TA_CENTER),
        'td_left':     s('td_left', fontSize=8, textColor=C_TEXT_DARK,
                         fontName='Helvetica', alignment=TA_LEFT),
    }


def _section_header(title, ST):
    """Returns a coloured section header block."""
    p = Paragraph(f"▌  {title}", ST['section_hdr'])
    tbl = Table([[p]], colWidths=[PAGE_W - 2 * MARGIN])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), C_BG_MID),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
    ]))
    return [tbl, Spacer(1, 4)]


def _kv_table(pairs, ST, cols=3):
    """Renders a compact key-value grid."""
    cells = []
    for label, val in pairs:
        cells.append([
            Paragraph(label, ST['label']),
            Paragraph(str(val), ST['value'])
        ])
    # Pad to full rows
    while len(cells) % cols != 0:
        cells.append([Paragraph('', ST['label']), Paragraph('', ST['value'])])

    col_w = (PAGE_W - 2 * MARGIN) / cols
    rows = [cells[i:i+cols] for i in range(0, len(cells), cols)]
    flat = [[cell for pair in row for cell in pair] for row in rows]
    col_widths = [col_w * 0.35, col_w * 0.65] * cols

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
    """Renders a dense data table with alternating row colours."""
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
    """Convert a matplotlib figure to a ReportLab Image flowable."""
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
    """Line chart of rating evolution over time."""
    fig, ax = plt.subplots(figsize=(10, 2.8), facecolor='#0f172a')
    ax.set_facecolor('#1e293b')

    values = [100.0] + [e.get('new_value', 100.0) for e in history]
    labels = ['Start'] + [
        _parse_ts(e.get('timestamp', '')).strftime('%b %d') if _parse_ts(e.get('timestamp', '')) else f'M{i+1}'
        for i, e in enumerate(history)
    ]

    x = list(range(len(values)))
    ax.plot(x, values, color='#3b82f6', linewidth=1.5, marker='o', markersize=3)
    ax.fill_between(x, values, min(values) - 5, alpha=0.15, color='#3b82f6')
    ax.axhline(100.0, color='#64748b', linewidth=0.7, linestyle='--', label='Baseline (100)')

    # Colour positive/negative segments
    for i in range(1, len(values)):
        c = '#10b981' if values[i] >= values[i-1] else '#ef4444'
        ax.plot([x[i-1], x[i]], [values[i-1], values[i]], color=c, linewidth=1.5)

    ax.set_xticks(x[::max(1, len(x)//10)])
    ax.set_xticklabels([labels[i] for i in x[::max(1, len(x)//10)]],
                       color='#94a3b8', fontsize=7, rotation=30, ha='right')
    ax.tick_params(axis='y', colors='#94a3b8', labelsize=7)
    ax.spines[:].set_color('#334155')
    ax.set_title('Rating Evolution', color='#e2e8f0', fontsize=9, pad=6)
    ax.set_ylabel('Rating', color='#94a3b8', fontsize=7)
    fig.tight_layout(pad=0.5)
    return fig


def _build_score_flow_chart(score_updates, title='Score Flow'):
    """Step chart of score progression during a match."""
    if not score_updates:
        return None
    fig, ax = plt.subplots(figsize=(8, 2.2), facecolor='#0f172a')
    ax.set_facecolor('#1e293b')

    t1 = [u['team1_score'] for u in score_updates]
    t2 = [u['team2_score'] for u in score_updates]
    x = list(range(len(score_updates)))

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
    """Bar chart of practice session hit rates over time."""
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
        return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    except Exception:
        return None


def _fmt_ts(ts_str):
    dt = _parse_ts(ts_str)
    return dt.strftime('%Y-%m-%d %H:%M') if dt else '—'


def _sign(v):
    return f'+{v:.2f}' if v >= 0 else f'{v:.2f}'


def _score_pattern(updates):
    """Classify a score sequence: dominant / comeback / collapse / close / normal."""
    if not updates or len(updates) < 3:
        return 'insufficient data'
    t1 = [u['team1_score'] for u in updates]
    t2 = [u['team2_score'] for u in updates]
    final_t1, final_t2 = t1[-1], t2[-1]
    winner = 1 if final_t1 > final_t2 else 2
    loser  = 2 if winner == 1 else 1

    # Dominant: winner led by ≥7 for most of the game
    winner_scores = t1 if winner == 1 else t2
    loser_scores  = t2 if winner == 1 else t1
    margins = [w - l for w, l in zip(winner_scores, loser_scores)]
    avg_margin = sum(margins) / len(margins)

    # Comeback: loser was ahead at some point
    loser_led = any(l > w for w, l in zip(winner_scores, loser_scores))

    # Close: final margin ≤ 2
    final_margin = abs(final_t1 - final_t2)

    if avg_margin >= 7:
        return 'dominant'
    if loser_led and final_margin <= 4:
        return 'comeback'
    if final_margin <= 2:
        return 'close'
    return 'normal'


def _get_player_ranking(player_profile):
    """Return (rank, total) for the player by rating."""
    try:
        all_profiles = PlayerProfile.objects.filter(
            value__isnull=False
        ).order_by('-value').values_list('id', flat=True)
        ids = list(all_profiles)
        rank = ids.index(player_profile.id) + 1
        return rank, len(ids)
    except Exception:
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# Section builders
# ─────────────────────────────────────────────────────────────────────────────
def _section_identity(player, profile, ST, elements):
    elements += _section_header('1. PLAYER IDENTITY & OVERVIEW', ST)

    rank, total = _get_player_ranking(profile)
    rank_str = f'#{rank} / {total}' if rank else 'N/A'

    trend_data = profile.get_rating_trend(last_n_matches=10)
    trend_str = f"{trend_data['trend'].upper()} ({_sign(trend_data['change'])} over last {trend_data['matches']} matches)"

    level_map = {1: 'Beginner', 2: 'Intermediate', 3: 'Advanced', 4: 'Expert', 5: 'Professional'}
    level_str = level_map.get(profile.skill_level, 'Unknown')

    pairs = [
        ('Player Name',        player.name),
        ('Player ID',          str(player.id)),
        ('Codename (internal)',player.codename if hasattr(player, 'codename') else '—'),
        ('Current Rating',     f'{profile.value:.2f}'),
        ('Global Ranking',     rank_str),
        ('Skill Level',        level_str),
        ('Preferred Position', (profile.preferred_position or '—').capitalize()),
        ('Matches Played',     str(profile.matches_played)),
        ('Matches Won',        str(profile.matches_won)),
        ('Win Rate',           f'{round(profile.matches_won / profile.matches_played * 100, 1) if profile.matches_played else 0}%'),
        ('Rating vs Baseline', _sign(profile.value - 100.0)),
        ('Trend (last 10)',    trend_str),
    ]
    elements.append(_kv_table(pairs, ST, cols=3))
    elements.append(Spacer(1, 6))


def _section_rating(profile, ST, elements):
    elements += _section_header('2. RATING EVOLUTION & TREND ANALYSIS', ST)

    history = profile.rating_history or []
    if not history:
        elements.append(Paragraph('No rating history available.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    # Chart
    fig = _build_rating_chart(history)
    elements.append(_matplotlib_to_image(fig, width_mm=165))
    elements.append(Spacer(1, 4))

    # Statistics
    changes = [e.get('change', 0) for e in history]
    values  = [e.get('new_value', 100.0) for e in history]
    max_val = max(values)
    min_val = min(values)
    variance = float(np.var(changes)) if changes else 0.0
    std_dev  = float(np.std(changes)) if changes else 0.0

    # Win/loss streaks
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

    # Per-entry history table (last 20)
    elements.append(Spacer(1, 4))
    elements.append(Paragraph('Recent Rating History (last 20 entries)', ST['label']))
    headers = ['#', 'Date', 'Old', 'New', 'Change', 'Opp Rating', 'Score', 'Type']
    rows = []
    for i, e in enumerate(history[-20:], 1):
        rows.append([
            str(len(history) - 20 + i),
            _fmt_ts(e.get('timestamp', '')),
            f"{e.get('old_value', 0):.2f}",
            f"{e.get('new_value', 0):.2f}",
            _sign(e.get('change', 0)),
            f"{e.get('opponent_value', 0):.2f}",
            f"{e.get('own_score', '?')}-{e.get('opponent_score', '?')}",
            e.get('match_type', '—'),
        ])
    cw = [18*mm, 30*mm, 22*mm, 22*mm, 22*mm, 26*mm, 20*mm, 20*mm]
    elements.append(_data_table(headers, rows, ST, col_widths=cw))
    elements.append(Spacer(1, 6))


def _section_match_history(player, tournament_matches, ST, elements):
    elements += _section_header('3. TOURNAMENT MATCH HISTORY', ST)

    if not tournament_matches:
        elements.append(Paragraph('No tournament match history available.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    headers = ['Date', 'Tournament', 'Round', 'Opponent', 'Score', 'Result', 'Duration']
    rows = []
    for m in tournament_matches[:30]:
        result = 'WIN' if getattr(m, 'player_won', False) else 'LOSS'
        score = f"{getattr(m, 'player_score', '?')}-{getattr(m, 'opponent_score', '?')}"
        dur = '—'
        if m.duration:
            total_s = int(m.duration.total_seconds())
            dur = f"{total_s // 60}m {total_s % 60}s"
        date_str = m.end_time.strftime('%Y-%m-%d') if m.end_time else '—'
        rows.append([
            date_str,
            m.tournament.name[:22] if m.tournament else '—',
            str(m.round) if m.round else '—',
            getattr(m, 'opponent_name', '—')[:18],
            score,
            result,
            dur,
        ])
    cw = [24*mm, 44*mm, 20*mm, 36*mm, 18*mm, 16*mm, 18*mm]
    elements.append(_data_table(headers, rows, ST, col_widths=cw))
    elements.append(Spacer(1, 6))


def _section_score_progression(player, tournament_matches, ST, elements):
    elements += _section_header('4. SCORE PROGRESSION ANALYSIS (ScoreUpdate Log)', ST)

    from matches.models import LiveScoreboard, ScoreUpdate

    scored_matches = []
    for m in tournament_matches[:20]:
        try:
            sb = LiveScoreboard.objects.filter(match=m).first()
            if sb:
                updates = list(
                    ScoreUpdate.objects.filter(scoreboard=sb)
                    .order_by('timestamp')
                    .values('team1_score', 'team2_score', 'update_type', 'timestamp')
                )
                if updates:
                    scored_matches.append((m, updates))
        except Exception:
            pass

    if not scored_matches:
        elements.append(Paragraph('No score progression data available for recent matches.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    elements.append(Paragraph(
        f'Score progression data found for {len(scored_matches)} matches.',
        ST['body']
    ))
    elements.append(Spacer(1, 4))

    for m, updates in scored_matches[:6]:
        pattern = _score_pattern(updates)
        date_str = m.end_time.strftime('%Y-%m-%d') if m.end_time else '—'
        opp = getattr(m, 'opponent_name', '—')
        final = f"{updates[-1]['team1_score']}-{updates[-1]['team2_score']}"
        title = f"{date_str}  vs {opp}  [{final}]  Pattern: {pattern.upper()}"

        fig = _build_score_flow_chart(updates, title=title)
        if fig:
            elements.append(_matplotlib_to_image(fig, width_mm=155))
            elements.append(Spacer(1, 3))

        # Compact event table (corrections + resets only for density)
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


def _section_friendly_games(player, friendly_matches, ST, elements):
    elements += _section_header('5. FRIENDLY GAME HISTORY', ST)

    if not friendly_matches:
        elements.append(Paragraph('No friendly game history available.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    # Summary stats
    total = len(friendly_matches)
    wins  = sum(1 for m in friendly_matches if m.get('won'))
    wr    = round(wins / total * 100, 1) if total else 0

    pairs = [
        ('Total Friendly Games', str(total)),
        ('Wins', str(wins)),
        ('Losses', str(total - wins)),
        ('Win Rate', f'{wr}%'),
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
    elements.append(Spacer(1, 6))


def _section_tournament_breakdown(player, tournament_matches, ST, elements):
    elements += _section_header('6. TOURNAMENT BREAKDOWN', ST)

    if not tournament_matches:
        elements.append(Paragraph('No tournament data available.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    # Group by tournament
    by_tournament = defaultdict(list)
    for m in tournament_matches:
        t_name = m.tournament.name if m.tournament else 'Unknown'
        by_tournament[t_name].append(m)

    headers = ['Tournament', 'Played', 'Won', 'Lost', 'Win Rate', 'Avg Score', 'Avg Conceded']
    rows = []
    for t_name, matches in sorted(by_tournament.items()):
        played = len(matches)
        won    = sum(1 for m in matches if getattr(m, 'player_won', False))
        wr     = round(won / played * 100, 1) if played else 0
        scores    = [getattr(m, 'player_score', 0) for m in matches]
        conceded  = [getattr(m, 'opponent_score', 0) for m in matches]
        avg_s = round(sum(scores) / len(scores), 1) if scores else 0
        avg_c = round(sum(conceded) / len(conceded), 1) if conceded else 0
        rows.append([t_name[:30], str(played), str(won), str(played - won),
                     f'{wr}%', str(avg_s), str(avg_c)])
    cw = [55*mm, 18*mm, 16*mm, 16*mm, 20*mm, 22*mm, 22*mm]
    elements.append(_data_table(headers, rows, ST, col_widths=cw))
    elements.append(Spacer(1, 6))


def _section_practice(player, ST, elements):
    elements += _section_header('7. PRACTICE & SHOOTING SESSIONS', ST)

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

    sessions = list(PracticeSession.objects.filter(
        player_codename=codename
    ).order_by('-started_at')[:50])

    if not sessions:
        elements.append(Paragraph('No practice sessions recorded for this player.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    shooting_sessions = [s for s in sessions if s.practice_type == 'shooting']
    pointing_sessions = [s for s in sessions if s.practice_type == 'pointing']

    # Summary
    def _summarise(sess_list, ptype):
        if not sess_list:
            return []
        total_shots = sum(s.total_shots for s in sess_list)
        avg_rate    = round(sum(s.hit_percentage for s in sess_list) / len(sess_list), 1)
        best_rate   = round(max(s.hit_percentage for s in sess_list), 1)
        worst_rate  = round(min(s.hit_percentage for s in sess_list), 1)
        return [
            (f'{ptype} Sessions', str(len(sess_list))),
            (f'{ptype} Total Shots', str(total_shots)),
            (f'{ptype} Avg Success Rate', f'{avg_rate}%'),
            (f'{ptype} Best Session', f'{best_rate}%'),
            (f'{ptype} Worst Session', f'{worst_rate}%'),
        ]

    pairs = _summarise(shooting_sessions, 'Shooting') + _summarise(pointing_sessions, 'Pointing')
    if pairs:
        elements.append(_kv_table(pairs, ST, cols=3))
        elements.append(Spacer(1, 4))

    # Bar charts
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

    # Detailed session table
    elements.append(Paragraph('Recent Practice Sessions (last 20)', ST['label']))
    headers = ['Date', 'Type', 'Dist', 'Shots', 'Success%', 'Carreaux%', 'Miss%', 'Duration']
    rows = []
    for s in sessions[:20]:
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

    # Shooting-specific breakdown (outcome distribution)
    if shooting_sessions:
        elements.append(Spacer(1, 4))
        elements.append(Paragraph('Shooting Outcome Distribution (all sessions)', ST['label']))
        total_shots = sum(s.total_shots for s in shooting_sessions) or 1
        total_hits  = sum(s.hits for s in shooting_sessions)
        total_pc    = sum(s.petit_carreaux for s in shooting_sessions)
        total_c     = sum(s.carreaux for s in shooting_sessions)
        total_miss  = sum(s.misses for s in shooting_sessions)
        pairs2 = [
            ('Hits',          f'{total_hits} ({round(total_hits/total_shots*100,1)}%)'),
            ('Petit Carreaux',f'{total_pc} ({round(total_pc/total_shots*100,1)}%)'),
            ('Carreaux',      f'{total_c} ({round(total_c/total_shots*100,1)}%)'),
            ('Misses',        f'{total_miss} ({round(total_miss/total_shots*100,1)}%)'),
        ]
        elements.append(_kv_table(pairs2, ST, cols=4))

    if pointing_sessions:
        elements.append(Spacer(1, 4))
        elements.append(Paragraph('Pointing Outcome Distribution (all sessions)', ST['label']))
        total_shots = sum(s.total_shots for s in pointing_sessions) or 1
        total_p     = sum(s.perfects + s.petit_perfects for s in pointing_sessions)
        total_g     = sum(s.goods for s in pointing_sessions)
        total_f     = sum(s.fairs for s in pointing_sessions)
        total_far   = sum(s.fars for s in pointing_sessions)
        pairs3 = [
            ('Perfect/Petit Perfect', f'{total_p} ({round(total_p/total_shots*100,1)}%)'),
            ('Good',                  f'{total_g} ({round(total_g/total_shots*100,1)}%)'),
            ('Fair',                  f'{total_f} ({round(total_f/total_shots*100,1)}%)'),
            ('Far',                   f'{total_far} ({round(total_far/total_shots*100,1)}%)'),
        ]
        elements.append(_kv_table(pairs3, ST, cols=4))

    elements.append(Spacer(1, 6))


def _section_ecosystem(player, tournament_matches, friendly_matches, ST, elements):
    elements += _section_header('8. TEAMMATE & OPPONENT ECOSYSTEM', ST)

    from teams.models import Team

    teammate_stats  = defaultdict(lambda: {'games': 0, 'wins': 0})
    opponent_stats  = defaultdict(lambda: {'games': 0, 'wins': 0})

    for m in tournament_matches:
        won = getattr(m, 'player_won', False)
        player_team = getattr(m, 'player_team', None)
        if player_team is None:
            continue

        # Teammates: other players on the same team
        if player_team == m.team1:
            opp_team = m.team2
        else:
            opp_team = m.team1

        if opp_team:
            opp_name = opp_team.name
            opponent_stats[opp_name]['games'] += 1
            if won:
                opponent_stats[opp_name]['wins'] += 1

    if not opponent_stats:
        elements.append(Paragraph('Insufficient data for ecosystem analysis.', ST['body']))
        elements.append(Spacer(1, 6))
        return

    # Opponent table
    elements.append(Paragraph('Opponent Win Rate (tournament matches)', ST['label']))
    opp_rows = sorted(opponent_stats.items(), key=lambda x: -x[1]['games'])
    headers = ['Opponent', 'Games', 'Wins', 'Losses', 'Win Rate']
    rows = []
    for name, s in opp_rows[:20]:
        wr = round(s['wins'] / s['games'] * 100, 1) if s['games'] else 0
        rows.append([name[:30], str(s['games']), str(s['wins']),
                     str(s['games'] - s['wins']), f'{wr}%'])
    cw = [70*mm, 22*mm, 22*mm, 22*mm, 22*mm]
    elements.append(_data_table(headers, rows, ST, col_widths=cw))
    elements.append(Spacer(1, 6))


# ─────────────────────────────────────────────────────────────────────────────
# Cover page
# ─────────────────────────────────────────────────────────────────────────────
def _cover_page(player, profile, ST, elements):
    """Full-width dark cover block."""
    generated_at = timezone.now().strftime('%Y-%m-%d %H:%M UTC')

    cover_data = [[
        Paragraph('PFC — AI COACH REPORT', ST['cover_title']),
        Paragraph('Special Report for petA UMP AI Coach Analysis', ST['cover_sub']),
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
        ('ROUNDEDCORNERS',(0, 0), (-1, -1), [8, 8, 8, 8]),
    ]))
    elements.append(tbl)
    elements.append(Spacer(1, 10))


# ─────────────────────────────────────────────────────────────────────────────
# Main view
# ─────────────────────────────────────────────────────────────────────────────
def ai_coach_report(request, player_id):
    """
    Generate and stream the AI Coach Report PDF for a player.
    Access: own profile (session match) or staff.
    """
    player = get_object_or_404(
        Player.objects.select_related('profile', 'team'),
        id=player_id
    )

    # Access control: own profile or staff
    session_player_id = request.session.get('player_id')
    is_own = session_player_id is not None and int(session_player_id) == player.id
    is_staff = request.user.is_authenticated and request.user.is_staff
    if not (is_own or is_staff):
        raise Http404("Report not accessible.")

    profile = getattr(player, 'profile', None)
    if profile is None:
        raise Http404("Player profile not found.")

    # ── Gather data ──────────────────────────────────────────────────────────
    from django.db.models import Q
    from matches.models import Match

    # Tournament matches (reuse same logic as player_profile view)
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

    # Annotate player_team, player_won, opponent_name, scores
    try:
        from matches.models import MatchPlayer as _MP
        mp_map = {
            mp.match_id: mp.team
            for mp in _MP.objects.filter(
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
        m.player_team   = actual_team
        m.player_score  = p_score
        m.opponent_score= o_score
        m.opponent_name = opp_name
        m.player_won    = p_score > o_score

    # Friendly matches
    friendly_matches = []
    try:
        from friendly_games.models import FriendlyGamePlayer
        for fgp in FriendlyGamePlayer.objects.filter(
            player=player, codename_verified=True, game__status='COMPLETED'
        ).select_related('game').order_by('-game__created_at')[:40]:
            g = fgp.game
            friendly_matches.append({
                'date': g.created_at,
                'game_name': g.name,
                'team': fgp.team,
                'position': fgp.position,
                'black_score': g.black_team_score,
                'white_score': g.white_team_score,
                'won': fgp.games_won > 0,
                'game_id': g.id,
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
        title=f'PFC AI Coach Report — {player.name}',
        author='PFC Platform',
        subject='AI Coach Performance Dossier',
    )

    ST = _styles()
    elements = []

    _cover_page(player, profile, ST, elements)
    elements.append(PageBreak())

    _section_identity(player, profile, ST, elements)
    _section_rating(profile, ST, elements)
    elements.append(PageBreak())

    _section_match_history(player, tournament_matches, ST, elements)
    _section_score_progression(player, tournament_matches, ST, elements)
    elements.append(PageBreak())

    _section_friendly_games(player, friendly_matches, ST, elements)
    _section_tournament_breakdown(player, tournament_matches, ST, elements)
    elements.append(PageBreak())

    _section_practice(player, ST, elements)
    elements.append(PageBreak())

    _section_ecosystem(player, tournament_matches, friendly_matches, ST, elements)

    doc.build(elements)
    buf.seek(0)

    filename = f'PFC_AICoachReport_{player.name.replace(" ", "_")}_{timezone.now().strftime("%Y%m%d")}.pdf'
    response = HttpResponse(buf.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
