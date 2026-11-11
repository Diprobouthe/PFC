"""Regression coverage for AI Coach Report computations.

These tests use only in-memory records: no production data and no DB writes.
"""
from types import SimpleNamespace
from io import BytesIO
import os
from pathlib import Path
from unittest.mock import patch

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate
from pypdf import PdfReader

from django.test import SimpleTestCase, TestCase, RequestFactory

from teams.views_ai_report import (
    _aggregate_friendly_teammates,
    _load_pairwise_friendly_history,
    _summarize_pairwise_friendly_history,
    _rolling_pair_series,
    _compute_match_flow,
    _rating_delta_for_tournament_match,
    _rating_entry_type,
    _verified_score_updates,
    _best_verified_win_streak_from_rating_history,
    _section_data_quality,
    _section_practice,
    _section_ai_instructions,
    _section_friendly_teammates,
    _styles,
    MARGIN,
    ai_coach_report,
)


class CoachReportScoreFlowTests(SimpleTestCase):
    def test_post_match_reset_is_not_treated_as_result(self):
        updates = [
            {'team1_score': 0, 'team2_score': 0},
            {'team1_score': 4, 'team2_score': 4},
            {'team1_score': 9, 'team2_score': 5},
            {'team1_score': 0, 'team2_score': 0, 'update_type': 'correction'},
        ]
        history = _verified_score_updates(updates, 9, 5)
        self.assertEqual(history[-1]['team1_score'], 9)
        self.assertEqual(len(history), 3)
        flow = _compute_match_flow(history, 'team1')
        self.assertTrue(flow['player_won'])
        self.assertFalse(flow['lost_after_leading'])
        self.assertFalse(flow['close_finish'])
        self.assertEqual(flow['final_margin'], 4)

    def test_missing_official_final_omits_unverifiable_flow(self):
        updates = [{'team1_score': 3, 'team2_score': 2}]
        self.assertEqual(_verified_score_updates(updates, 13, 9), [])

    def test_same_score_correction_keeps_last_official_occurrence(self):
        updates = [
            {'team1_score': 9, 'team2_score': 5},
            {'team1_score': 1, 'team2_score': 1},
            {'team1_score': 9, 'team2_score': 5},
            {'team1_score': 0, 'team2_score': 0},
        ]
        self.assertEqual(len(_verified_score_updates(updates, 9, 5)), 3)


class CoachReportRatingAttributionTests(SimpleTestCase):
    def test_legacy_friendly_id_overrides_mislabeled_tournament_type(self):
        bad_legacy_entry = {
            'match_id': 'friendly_1882', 'match_type': 'tournament',
            'change': 1.5,
        }
        self.assertEqual(_rating_entry_type(bad_legacy_entry), 'friendly')
        self.assertEqual(_rating_entry_type({
            'match_id': 977, 'match_type': 'tournament'
        }), 'tournament')
        self.assertIsNone(_rating_delta_for_tournament_match(
            [bad_legacy_entry], 1882
        ))

    def test_exact_match_id_prevents_time_based_misattribution(self):
        history = [
            {'match_id': 'friendly_90', 'match_type': 'tournament', 'change': 4.5},
            {'match_id': 42, 'match_type': 'tournament', 'change': -1.25},
            {'match_id': 42, 'match_type': 'friendly', 'change': 7.0},
        ]
        self.assertEqual(_rating_delta_for_tournament_match(history, 42), -1.25)
        self.assertIsNone(_rating_delta_for_tournament_match(history, 90))


    
class CoachReportEvidenceSemanticsTests(SimpleTestCase):
    def test_win_streak_uses_scores_not_rating_change_sign(self):
        events = [
            {'own_score': 13, 'opponent_score': 7, 'change': -2},
            {'own_score': 13, 'opponent_score': 5, 'change': -3},
            {'own_score': 2, 'opponent_score': 13, 'change': 8},
            {'own_score': 13, 'opponent_score': 4, 'change': -1},
        ]
        self.assertEqual(_best_verified_win_streak_from_rating_history(events), 2)

    def test_unverifiable_scores_break_streak_not_invent_results(self):
        events = [
            {'own_score': 13, 'opponent_score': 7},
            {'own_score': 13, 'opponent_score': 7},
            {'change': 5.0},  # Missing score cannot extend a win streak.
            {'own_score': 13, 'opponent_score': 5},
            {'own_score': 13, 'opponent_score': 13},
            {'own_score': 13, 'opponent_score': 3},
        ]
        self.assertEqual(_best_verified_win_streak_from_rating_history(events), 2)
        self.assertIsNone(
            _best_verified_win_streak_from_rating_history([
                {'change': 8.0}, {'own_score': 'unknown', 'opponent_score': 13}
            ])
        )

    def test_intentional_rating_history_cap_is_not_data_loss(self):
        # A player may have 200 games but only 50 retained rating changes.
        player = SimpleNamespace(id=432)
        profile = SimpleNamespace(
            matches_played=200,
            rating_history=[{'match_id': i, 'match_type': 'tournament'}
                            for i in range(50)],
        )
        elements = []
        _section_data_quality(player, profile, [], {}, _styles(), elements)
        buf = BytesIO()
        SimpleDocTemplate(
            buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=MARGIN, bottomMargin=MARGIN,
        ).build(elements)
        extracted = PdfReader(BytesIO(buf.getvalue())).pages[0].extract_text()
        self.assertIn('No data quality issues detected.', extracted)
        self.assertNotIn('may be missing', extracted)
        self.assertNotIn('Difference:', extracted)


class CoachReportFriendlyTeammateTests(SimpleTestCase):
    @staticmethod
    def mate(game_id, player_id, name, team='BLACK', verified=True, position='TIRER'):
        return SimpleNamespace(
            game_id=game_id, player_id=player_id,
            player=SimpleNamespace(name=name), team=team,
            codename_verified=verified, position=position,
        )

    def test_only_verified_same_side_teammates_are_counted(self):
        friendlies = [
            {'game_id': 1, 'team': 'BLACK', 'black_score': 13,
             'white_score': 7, 'position': 'POINTEUR'},
            {'game_id': 2, 'team': 'BLACK', 'black_score': 13,
             'white_score': 9, 'position': 'POINTEUR'},
            {'game_id': 3, 'team': 'BLACK', 'black_score': 8,
             'white_score': 13, 'position': 'MILIEU'},
            {'game_id': 4, 'team': 'WHITE', 'black_score': 13,
             'white_score': 13, 'position': 'POINTEUR'},
        ]
        roster = [
            self.mate(1, 22, 'Teammate'),
            self.mate(2, 22, 'Teammate'),
            self.mate(3, 22, 'Teammate'),
            self.mate(1, 23, 'Opposition', team='WHITE'),
            self.mate(2, 24, 'Unverified', verified=False),
            self.mate(3, 11, 'Self'),
            self.mate(4, 22, 'Teammate'),
        ]
        stats = _aggregate_friendly_teammates(11, friendlies, roster)
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]['name'], 'Teammate')
        self.assertEqual(stats[0]['games'], 3)
        self.assertEqual(stats[0]['wins'], 2)
        self.assertEqual(stats[0]['score_diff_total'], 5)  # +6 +4 -5
        self.assertEqual(stats[0]['roles']['POINTEUR / TIRER'], 2)
        self.assertEqual(stats[0]['roles']['MILIEU / TIRER'], 1)

    def test_teammates_with_same_name_remain_separate(self):
        friendly = [{'game_id': 1, 'team': 'WHITE', 'black_score': 4,
                     'white_score': 13, 'position': 'MILIEU'}]
        roster = [
            self.mate(1, 21, 'Alex', team='WHITE'),
            self.mate(1, 22, 'Alex', team='WHITE'),
        ]
        self.assertEqual(len(_aggregate_friendly_teammates(11, friendly, roster)), 2)

    def test_pdf_smoke_renders_friendly_teammate_table_and_summary(self):
        # Include markup characters and Greek characters found in real names.
        sample_name = 'Μαρία & Γιάννης <Coach>'
        friendlies = [
            {'game_id': i, 'team': 'BLACK', 'black_score': 13,
             'white_score': 5, 'position': 'POINTEUR'}
            for i in (1, 2, 3)
        ]
        roster = [self.mate(i, 23, sample_name) for i in (1, 2, 3)]
        pair_rows = [{
            'game_id': i, 'date': None, 'teammate_id': 23,
            'name': sample_name, 'team': 'BLACK', 'position': 'POINTEUR',
            'teammate_position': 'TIRER',
            'black_score': 13, 'white_score': 5,
        } for i in (1, 2, 3)]
        elements = []
        _section_friendly_teammates(
            SimpleNamespace(id=11), friendlies, _styles(), elements,
            pair_rows=pair_rows,
        )
        buf = BytesIO()
        SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN).build(elements)
        pdf = buf.getvalue()
        self.assertTrue(pdf.startswith(b'%PDF-'))
        extracted = PdfReader(BytesIO(pdf)).pages[0].extract_text()
        self.assertIn('10a. FRIENDLY PARTNERSHIP TRAJECTORIES', extracted)
        self.assertIn('Μαρία', extracted)
        self.assertIn('Γιάννης', extracted)

    
    def test_rolling_pair_window_tracks_joint_results(self):
        history = [
            {'win': w, 'margin': d}
            for w, d in [(1, 7), (1, 4), (0, -6), (1, 2), (0, -5), (0, -8), (1, 3)]
        ]
        curve = _rolling_pair_series(history)
        self.assertEqual(len(curve), 3)
        self.assertEqual(curve[0][0], 5)
        self.assertEqual(curve[0][1], 60.0)
        self.assertEqual(curve[-1][1], 40.0)
        self.assertAlmostEqual(curve[-1][2], -2.8)

    def test_pair_rating_coverage_does_not_fill_missing_history(self):
        rows = [
            {'game_id': 1, 'date': None, 'teammate_id': 22, 'name': 'Alex',
             'team': 'BLACK', 'position': 'POINTEUR', 'teammate_position': 'TIRER',
             'black_score': 13, 'white_score': 7},
            {'game_id': 2, 'date': None, 'teammate_id': 22, 'name': 'Alex',
             'team': 'BLACK', 'position': 'POINTEUR', 'teammate_position': 'TIRER',
             'black_score': 3, 'white_score': 13},
            {'game_id': 3, 'date': None, 'teammate_id': 23, 'name': 'Alex',
             'team': 'WHITE', 'position': 'MILIEU', 'teammate_position': 'TIRER',
             'black_score': 6, 'white_score': 13},
        ]
        data = _summarize_pairwise_friendly_history(rows, {1: 144.0})
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['teammate_id'], 22)
        self.assertEqual(data[0]['games'], 2)
        self.assertEqual(data[0]['wins'], 1)
        self.assertEqual(data[0]['opponent_rating_count'], 1)
        self.assertEqual(data[1]['games'], 1)
        self.assertEqual(data[1]['wins'], 1)


    def test_partnership_chart_embeds_into_pdf_with_ten_joint_games(self):
        partner_rows = [
            {
                'game_id': idx, 'date': None, 'teammate_id': 23,
                'name': 'Partner 23', 'team': 'BLACK',
                'position': 'POINTEUR', 'teammate_position': 'MILIEU',
                'black_score': 13 if idx % 3 else 4,
                'white_score': 7 if idx % 3 else 13,
            }
            for idx in range(1, 13)
        ]
        elements = []
        _section_friendly_teammates(
            SimpleNamespace(id=11), [], _styles(), elements,
            pair_rows=partner_rows,
        )
        images = [e for e in elements if e.__class__.__name__ == 'Image']
        self.assertTrue(images)
        # A 2:1 landscape chart must not get stretched into a portrait image.
        self.assertLess(images[0].drawHeight, images[0].drawWidth)
        buf = BytesIO()
        SimpleDocTemplate(
            buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=MARGIN, bottomMargin=MARGIN,
        ).build(elements)
        doc = PdfReader(BytesIO(buf.getvalue()))
        self.assertGreaterEqual(len(doc.pages), 1)


class CoachReportFriendlyTeammateDatabaseTests(TestCase):
    """Real ORM join and PDF smoke against Django's temporary test database."""

    def test_friendly_roster_queries_and_pdf_generation(self):
        from teams.models import Team, Player
        from friendly_games.models import FriendlyGame, FriendlyGamePlayer

        home = Team.objects.create(name='AI Coach test team', pin='AC1234')
        subject = Player.objects.create(name='Reporter', team=home)
        partner = Player.objects.create(name='Verified partner', team=home)
        unknown = Player.objects.create(name='Unverified player', team=home)
        game_rows = []
        for index, (black, white) in enumerate([(13, 7), (13, 8), (3, 13)], 1):
            game = FriendlyGame.objects.create(
                name=f'AI Coach fixture {index}',
                match_number=f'9{index:03d}',
                status='COMPLETED',
                black_team_score=black,
                white_team_score=white,
            )
            FriendlyGamePlayer.objects.create(
                game=game, player=subject, team='BLACK',
                position='POINTEUR', codename_verified=True,
            )
            FriendlyGamePlayer.objects.create(
                game=game, player=partner, team='BLACK',
                position='TIRER', codename_verified=True,
            )
            FriendlyGamePlayer.objects.create(
                game=game, player=unknown, team='WHITE',
                position='MILIEU', codename_verified=False,
            )
            game_rows.append({
                'game_id': game.id, 'team': 'BLACK',
                'position': 'POINTEUR',
                'black_score': black, 'white_score': white,
            })

        pair_rows = _load_pairwise_friendly_history(subject.id)
        self.assertEqual(len(pair_rows), 3)
        self.assertEqual({r['teammate_id'] for r in pair_rows}, {partner.id})
        stats = _summarize_pairwise_friendly_history(pair_rows)
        self.assertEqual(stats[0]['wins'], 2)

        elements = []
        _section_friendly_teammates(subject, game_rows, _styles(), elements)
        buffer = BytesIO()
        SimpleDocTemplate(
            buffer, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=MARGIN, bottomMargin=MARGIN
        ).build(elements)
        extracted = PdfReader(BytesIO(buffer.getvalue())).pages[0].extract_text()
        self.assertIn('Verified partner', extracted)
        self.assertIn('66.7%', extracted)
        self.assertNotIn('Unverified player', extracted)

    def test_last_50_are_scoped_to_each_pair_not_last_50_personal_games(self):
        from teams.models import Team, Player
        from friendly_games.models import FriendlyGame, FriendlyGamePlayer

        team = Team.objects.create(name='Bounded partnership test', pin='BP1234')
        subject = Player.objects.create(name='Subject', team=team)
        frequent = Player.objects.create(name='Frequent partner', team=team)
        newer = Player.objects.create(name='Newer partner', team=team)

        # 55 old joint games with A, then 10 newer games with B.
        # An incorrect "latest 50 personal games" implementation would
        # discard 15 relevant A games, despite their pair-history being valid.
        games = FriendlyGame.objects.bulk_create([
            FriendlyGame(
                name=f'Pairwise {n}', match_number=f'8{n:03d}',
                status='COMPLETED', black_team_score=13,
                white_team_score=(2 if n < 5 else 8),
            )
            for n in range(65)
        ])
        memberships = []
        for n, game in enumerate(games):
            memberships.append(FriendlyGamePlayer(
                game=game, player=subject, team='BLACK',
                position='POINTEUR', codename_verified=True,
            ))
            memberships.append(FriendlyGamePlayer(
                game=game, player=frequent if n < 55 else newer,
                team='BLACK', position='TIRER', codename_verified=True,
            ))
        FriendlyGamePlayer.objects.bulk_create(memberships)

        rows = _load_pairwise_friendly_history(subject.id, limit=50)
        by_mate = {
            player.id: [r for r in rows if r['teammate_id'] == player.id]
            for player in (frequent, newer)
        }
        self.assertEqual(len(by_mate[frequent.id]), 50)
        self.assertEqual(len(by_mate[newer.id]), 10)
        self.assertEqual(
            {r['game_id'] for r in by_mate[frequent.id]},
            {game.id for game in games[5:55]},
        )
        self.assertEqual(
            {r['game_id'] for r in by_mate[newer.id]},
            {game.id for game in games[55:]},
        )


class CoachReportPointingSemanticsTests(TestCase):
    def test_ai_coach_pdf_uses_positive_perfect_good_negative_fair_far(self):
        from datetime import timedelta
        from django.utils import timezone
        from teams.models import Team, Player
        from friendly_games.models import PlayerCodename
        from practice.models import PracticeSession

        team = Team.objects.create(name='Pointing AI semantics fixture', pin='PFA100')
        player = Player.objects.create(name='Pointing Coach Fixture', team=team)
        PlayerCodename.objects.create(player=player, codename='POINTING_ING_TEST')
        now = timezone.now()
        training = PracticeSession.objects.create(
            player_codename='POINTING_ING_TEST', practice_type='pointing',
            distance='7m', total_shots=4, perfects=1, goods=1, fairs=1, fars=1,
            ended_at=now, is_active=False,
        )
        PracticeSession.objects.filter(pk=training.pk).update(started_at=now - timedelta(minutes=5))
        PracticeSession.objects.create(
            player_codename='POINTING_ING_TEST', practice_type='pointing',
            distance='ing', total_shots=4, perfects=1, goods=1, fairs=1, fars=1,
            ended_at=now, is_active=False,
        )
        elements = []
        styles = _styles()
        _section_ai_instructions(styles, elements)
        _section_practice(player, styles, elements)
        output = BytesIO()
        SimpleDocTemplate(output, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                          topMargin=MARGIN, bottomMargin=MARGIN).build(elements)
        text = ' '.join(' '.join((page.extract_text() or '').split()) for page in PdfReader(BytesIO(output.getvalue())).pages)
        self.assertIn('ING Pointing Success%', text)
        self.assertIn('50.0%', text)
        self.assertNotIn('75.0%', text)
        self.assertIn('Fair and Far are both unsuccessful', text)
        self.assertIn('Never interpret Fair as a positive result', text)


class CoachReportWholePdfTests(TestCase):
    """Full, synthetic report preview. No production database connection."""

    def test_complete_ai_coach_report_pdf_with_pairwise_curves(self):
        from teams.models import Team, Player, PlayerProfile
        from friendly_games.models import FriendlyGame, FriendlyGamePlayer

        home = Team.objects.create(name='PREVIEW Team', pin='PV1234')
        subject = Player.objects.create(name='Preview Player', team=home)
        alpha = Player.objects.create(name='Partner Alpha', team=home)
        beta = Player.objects.create(name='Περικλής Δοκιμή', team=home)
        rival = Player.objects.create(name='Opposing Player', team=home)
        PlayerProfile.objects.get_or_create(
            player=subject, defaults={'value': 128.5}
        )

        games = FriendlyGame.objects.bulk_create([
            FriendlyGame(
                name=f'Synthetic Collaboration {n + 1}',
                match_number=f'7{n:03d}',
                status='COMPLETED',
                black_team_score=13 if n % 4 else 6,
                white_team_score=5 if n % 4 else 13,
            )
            for n in range(27)
        ])
        participants = []
        for n, game in enumerate(games):
            participants.extend([
                FriendlyGamePlayer(
                    game=game, player=subject, team='BLACK',
                    position='POINTEUR', codename_verified=True,
                    games_won=1 if n % 4 else 0,
                ),
                FriendlyGamePlayer(
                    game=game, player=alpha if n < 15 else beta,
                    team='BLACK', position='TIRER', codename_verified=True,
                ),
                FriendlyGamePlayer(
                    game=game, player=rival, team='WHITE',
                    position='MILIEU', codename_verified=True,
                ),
            ])
        FriendlyGamePlayer.objects.bulk_create(participants)

        request = RequestFactory().get('/internal/ai-coach-preview/')
        request.user = SimpleNamespace(is_authenticated=True, is_staff=True)
        request.session = {}
        response = ai_coach_report(request, subject.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        content = response.content
        self.assertTrue(content.startswith(b'%PDF-'))
        pages = PdfReader(BytesIO(content)).pages
        self.assertGreaterEqual(len(pages), 8)
        text = '\n'.join(page.extract_text() or '' for page in pages)
        self.assertIn('FRIENDLY PARTNERSHIP TRAJECTORIES', text)
        self.assertIn('Partner Alpha', text)
        self.assertIn('Περικλής Δοκιμή', text)
        self.assertIn('Skill*', text)
        self.assertIn('Profile skill is not derived from the rating', text)
        self.assertIn('default/unverified', text)
        self.assertIn('PFC starts every player at rating 100', text)
        self.assertIn('No rating history available.', text)
        # Partner table and trajectory chart belong on one page together.
        partnership_pages = [
            page for page in pages
            if '10a. FRIENDLY PARTNERSHIP TRAJECTORIES'
            in (page.extract_text() or '')
        ]
        self.assertEqual(len(partnership_pages), 1)
        self.assertGreaterEqual(len(partnership_pages[0].images), 1)
        # A synthetic preview must never be populated using live player data.
        outdir = os.environ.get('PFC_AI_COACH_PREVIEW_DIR')
        if outdir:
            target = Path(outdir)
            target.mkdir(parents=True, exist_ok=True)
            (target / 'ai-coach-synthetic-full-report.pdf').write_bytes(content)
