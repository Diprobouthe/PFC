"""Regression coverage for AI Coach Report computations.

These tests use only in-memory records: no production data and no DB writes.
"""
from types import SimpleNamespace
from io import BytesIO
from unittest.mock import patch

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate
from pypdf import PdfReader

from django.test import SimpleTestCase, TestCase

from teams.views_ai_report import (
    _aggregate_friendly_teammates,
    _compute_match_flow,
    _rating_delta_for_tournament_match,
    _rating_entry_type,
    _verified_score_updates,
    _section_friendly_teammates,
    _styles,
    MARGIN,
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
        with patch('friendly_games.models.FriendlyGamePlayer.objects.filter') as query:
            query.return_value.select_related.return_value = roster
            elements = []
            _section_friendly_teammates(
                SimpleNamespace(id=11), friendlies, _styles(), elements
            )
        buf = BytesIO()
        SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN).build(elements)
        pdf = buf.getvalue()
        self.assertTrue(pdf.startswith(b'%PDF-'))
        self.assertIn('10a. FRIENDLY GAME TEAMMATE COMPATIBILITY',
                      PdfReader(BytesIO(pdf)).pages[0].extract_text())


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
