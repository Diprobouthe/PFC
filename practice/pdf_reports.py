"""Shareable PFC practice-session PDF, built from the recorded session data.

Independent of browser print/save dialogs: the same PDF bytes can be downloaded
or shared as a file through the native mobile Web Share API.
"""
from io import BytesIO

from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer

from pfc_core.pdf_reporting import header, heading, page_footer, table, text
from practice.utils import calculate_session_summary


GUIDED_DRILLS = {'tir_de_precision', 'tactical', 'sequence', 'hidden_target'}


def _shot_label(shot):
    # Historical Fair has no declared display choice in some PFC versions.
    return 'Fair' if shot.outcome == 'fair' else shot.get_outcome_display()


def render_practice_summary_pdf(session):
    """Return complete PDF bytes for this practice session (including shot order)."""
    shots = list(session.shots.order_by('sequence_number'))
    summary = calculate_session_summary(session)
    period = timezone.localtime(session.started_at).strftime('%d/%m/%Y %H:%M')

    # A shareable report should show the player's public name, not expose the
    # codename used to access their PFC practice sessions.
    from friendly_games.models import PlayerCodename
    link = PlayerCodename.objects.filter(codename=session.player_codename).select_related('player').first()
    player_name = link.player.name if link and link.player else 'PFC player'

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=13 * mm, bottomMargin=18 * mm,
        title='PFC Practice Summary', author='PFC',
    )
    type_label = 'Pointing' if session.practice_type == 'pointing' else 'Shooting'
    drill_label = (
        session.get_drill_type_display()
        if session.drill_type else type_label
    )
    story = header(
        'PFC - Practice Summary',
        f'{player_name} | {type_label} | {period}',
    )
    story.append(heading('Session'))
    metadata = [
        ['Field', 'Value'],
        ['Practice', drill_label],
        ['Date', period],
        ['Duration', summary['duration']],
        ['Shots recorded', str(len(shots))],
    ]
    if session.drill_type not in GUIDED_DRILLS:
        metadata.append(['Distance', session.distance or '—'])
        metadata.append(['Sequence tracking', 'ON' if session.sequence_tracking else 'OFF'])
    if session.court_complex_id:
        metadata.append(['Venue', session.court_complex.name])
    if session.court:
        metadata.append(['Court', session.court])
    if session.terrain:
        metadata.append(['Terrain', session.terrain])
    story.append(table(metadata, [48 * mm, 132 * mm]))
    story.append(Spacer(1, 4 * mm))

    story.append(heading('Performance'))
    if session.drill_type in GUIDED_DRILLS:
        rows = [
            ['Metric', 'Value'],
            ['Score', f'{session.tdp_score} / 100'],
            ['Shots', str(session.total_shots)],
        ]
    else:
        rows = [
            ['Metric', 'Value'],
            ['Shots', str(session.total_shots)],
            ['Success rate', f"{summary['hit_percentage']:.1f}%"],
            ['Longest successful streak', str(summary['longest_streak'])],
            ['First unsuccessful shot', str(summary['first_miss_position'] or '—')],
        ]
        if session.practice_type == 'pointing':
            rows.extend([
                ['Perfect', str(session.perfects)],
                ['Good', str(session.goods)],
                ['Fair (unsuccessful)', str(session.fairs)],
                ['Far (unsuccessful)', str(session.fars)],
            ])
            if session.petit_perfects:
                rows.append(['Petit Perfect (legacy)', str(session.petit_perfects)])
            story.append(text('Pointing successes: Perfect + Good (legacy Petit Perfect also counts). Fair and Far are unsuccessful.', size=8))
        else:
            rows.extend([
                ['Carreau', str(session.carreaux)],
                ['Petit Carreau', str(session.petit_carreaux)],
                ['Hit', str(session.hits)],
                ['Miss', str(session.misses)],
            ])
    story.append(table(rows, [65 * mm, 115 * mm]))
    story.append(Spacer(1, 3 * mm))

    if session.drill_type not in GUIDED_DRILLS and summary.get('performance_note'):
        story.append(heading('Performance notes'))
        story.append(text(summary['performance_note']))

    story.append(heading('Recorded shot sequence'))
    if not shots:
        story.append(text('No individual shots were recorded. No sequence is available.'))
    elif session.drill_type in GUIDED_DRILLS:
        rows = [['#', 'Outcome', 'Atelier', 'Distance', 'Points']]
        for shot in shots:
            rows.append([
                str(shot.sequence_number),
                _shot_label(shot),
                str(shot.atelier) if shot.atelier is not None else '—',
                shot.shot_distance or '—',
                str(shot.tdp_points),
            ])
        story.append(table(rows, [12 * mm, 80 * mm, 24 * mm, 32 * mm, 32 * mm]))
    else:
        # Compact, searchable text: the order is preserved and each outcome has
        # a numbered label, even when the mobile browser cannot print emojis.
        rows = [['Shots', 'Outcomes (in recording order)']]
        for start in range(0, len(shots), 6):
            group = shots[start:start + 6]
            labels = '  |  '.join(
                f"#{shot.sequence_number} {_shot_label(shot)}"
                for shot in group
            )
            rows.append([f'{group[0].sequence_number}-{group[-1].sequence_number}', labels])
        story.append(table(rows, [24 * mm, 156 * mm]))
        if not session.sequence_tracking:
            story.append(text(
                'Sequence tracking was OFF: display order follows the stored '
                'recording order and is not independently verified as throw order.',
                size=7,
            ))

    if session.notes:
        story.append(Spacer(1, 3 * mm))
        story.append(heading('Notes'))
        story.append(text(session.notes))

    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    return buffer.getvalue()
