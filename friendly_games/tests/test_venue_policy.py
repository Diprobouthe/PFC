from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from billboard.models import BillboardEntry
from courts.models import Court, CourtComplex
from friendly_games.court_utils import resolve_court_assignment
from friendly_games.models import FriendlyGame, PlayerCodename
from friendly_games.venue_utils import FriendlyVenueError, get_allowed_friendly_complexes
from teams.models import Player, Team


class FriendlyVenuePolicyTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.team = Team.objects.create(name='Venue Policy Team')
        self.creator = Player.objects.create(name='Venue Creator', team=self.team)
        self.codename = PlayerCodename.objects.create(player=self.creator, codename='VENU01')

        self.ioannina = CourtComplex.objects.create(
            name='Ioannina Courts',
            description='',
            latitude='39.665000',
            longitude='20.853000',
        )
        self.pedion_areos = CourtComplex.objects.create(
            name='Pedion Areos Courts',
            description='',
            latitude='37.992000',
            longitude='23.734000',
        )
        self.virtual = CourtComplex.objects.create(
            name='Non-geolocated Courts',
            description='',
        )
        self.ioannina_court = Court.objects.create(number=701)
        self.pedion_areos_court = Court.objects.create(number=702)
        self.virtual_court = Court.objects.create(number=703)
        self.ioannina.courts.add(self.ioannina_court)
        self.pedion_areos.courts.add(self.pedion_areos_court)
        self.virtual.courts.add(self.virtual_court)

    def _login_creator(self):
        session = self.client.session
        session['player_codename'] = self.codename.codename
        session['session_active'] = True
        session.save()

    def _creator_request(self):
        request = self.factory.get('/')
        SessionMiddleware(lambda req: None).process_request(request)
        request.session['player_codename'] = self.codename.codename
        request.session['session_active'] = True
        request.session.save()
        return request

    def _manual_gps_presence_at_ioannina(self, source=BillboardEntry.PRESENCE_SOURCE_MANUAL):
        return BillboardEntry.objects.create(
            codename=self.codename.codename,
            action_type='AT_COURTS',
            court_complex=self.ioannina,
            presence_source=source,
            is_active=True,
            created_at=timezone.now(),
        )

    def test_creator_without_current_gps_presence_can_use_only_virtual_complex(self):
        self._login_creator()

        allowed = get_allowed_friendly_complexes(self._creator_request())

        self.assertEqual([complex.pk for complex in allowed], [self.virtual.pk])

    def test_creator_with_manual_gps_presence_can_use_exact_physical_and_virtual_complexes(self):
        self._login_creator()
        self._manual_gps_presence_at_ioannina()

        allowed = get_allowed_friendly_complexes(self._creator_request())

        self.assertEqual(
            {complex.pk for complex in allowed},
            {self.ioannina.pk, self.virtual.pk},
        )
        self.assertNotIn(self.pedion_areos.pk, {complex.pk for complex in allowed})

    def test_game_generated_presence_does_not_authorize_a_physical_venue(self):
        self._login_creator()
        self._manual_gps_presence_at_ioannina(BillboardEntry.PRESENCE_SOURCE_FRIENDLY)

        allowed = get_allowed_friendly_complexes(self._creator_request())

        self.assertEqual([complex.pk for complex in allowed], [self.virtual.pk])

    def test_explicit_court_from_other_complex_is_rejected_not_used_as_override(self):
        self._login_creator()
        self._manual_gps_presence_at_ioannina()
        request = self._creator_request()
        allowed = get_allowed_friendly_complexes(request)

        with self.assertRaises(FriendlyVenueError):
            resolve_court_assignment(
                request,
                allowed_complexes=allowed,
                complex_id=self.ioannina.pk,
                court_id=self.pedion_areos_court.pk,
            )

    def test_automatic_court_stays_in_selected_permitted_complex(self):
        self._login_creator()
        self._manual_gps_presence_at_ioannina()
        request = self._creator_request()
        allowed = get_allowed_friendly_complexes(request)

        complex, court = resolve_court_assignment(
            request,
            allowed_complexes=allowed,
            complex_id=self.ioannina.pk,
        )

        self.assertEqual(complex.pk, self.ioannina.pk)
        self.assertEqual(court.pk, self.ioannina_court.pk)
        self.assertTrue(complex.courts.filter(pk=court.pk).exists())

    def test_creation_endpoint_rejects_a_physical_complex_without_creator_gps_presence(self):
        self._login_creator()

        response = self.client.post(reverse('friendly_games:create_game'), {
            'game_name': 'Unauthorized Physical Friendly',
            'creator_codename': self.codename.codename,
            'creator_position': 'milieu',
            'setup_mode': 'manual',
            'manual_assignments': '[]',
            'scanned_player_ids': '[]',
            'court_player_ids': '[]',
            'include_creator': '1',
            'court_complex_id': str(self.ioannina.pk),
            'court_id': str(self.ioannina_court.pk),
        }, follow=True)

        self.assertEqual(FriendlyGame.objects.count(), 0)
        self.assertContains(response, 'not permitted for this Friendly Game')

    def test_creation_endpoint_rejects_a_cross_complex_court_submission(self):
        self._login_creator()
        self._manual_gps_presence_at_ioannina()

        response = self.client.post(reverse('friendly_games:create_game'), {
            'game_name': 'Invalid Cross Complex Friendly',
            'creator_codename': self.codename.codename,
            'creator_position': 'milieu',
            'setup_mode': 'manual',
            'manual_assignments': '[]',
            'scanned_player_ids': '[]',
            'court_player_ids': '[]',
            'include_creator': '1',
            'court_complex_id': str(self.ioannina.pk),
            'court_id': str(self.pedion_areos_court.pk),
        }, follow=True)

        self.assertEqual(FriendlyGame.objects.count(), 0)
        self.assertContains(response, 'does not belong to the selected Court Complex')

    def test_creation_form_shows_only_the_creator_physical_and_virtual_complexes(self):
        self._login_creator()
        self._manual_gps_presence_at_ioannina()

        response = self.client.get(reverse('friendly_games:create_game'))

        self.assertContains(response, self.ioannina.name)
        self.assertContains(response, self.virtual.name)
        self.assertNotContains(response, self.pedion_areos.name)
