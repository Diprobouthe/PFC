from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billboard.community_presence import CommunityPresenceReport
from billboard.models import BillboardEntry
from courts.models import Court, CourtComplex


class CourtComplexDetailLiveContextTests(TestCase):
    def setUp(self):
        self.physical = CourtComplex.objects.create(
            name='Ioannina Courts',
            description='A physical venue for focused detail-page tests.',
            latitude='39.665000',
            longitude='20.853000',
        )
        self.virtual = CourtComplex.objects.create(
            name='Online venue',
            description='A non-geolocated venue for focused detail-page tests.',
        )
        self.court = Court.objects.create(number=9071, name='Ioannina Court 1')
        self.physical.courts.add(self.court)

    def test_physical_complex_uses_current_billboard_data_for_that_complex(self):
        here = BillboardEntry.objects.create(
            codename='HERE01',
            action_type='AT_COURTS',
            court_complex=self.physical,
            presence_source=BillboardEntry.PRESENCE_SOURCE_MANUAL,
        )
        going = BillboardEntry.objects.create(
            codename='GOING1',
            action_type='GOING_TO_COURTS',
            court_complex=self.physical,
            scheduled_date=timezone.now().date(),
            arrival_at=timezone.now() + timedelta(minutes=20),
        )
        CommunityPresenceReport.objects.create(
            court_complex=self.physical,
            reported_count=11,
            confirmation_count=3,
            last_reporter_codename='HERE01',
            confirming_codenames='HERE01,GOING1,OTHER1',
        )
        other_complex = CourtComplex.objects.create(
            name='Other physical venue',
            description='Separate source-isolation test venue.',
            latitude='37.983000',
            longitude='23.727000',
        )
        BillboardEntry.objects.create(
            codename='OTHER1',
            action_type='AT_COURTS',
            court_complex=other_complex,
            presence_source=BillboardEntry.PRESENCE_SOURCE_MANUAL,
        )

        response = self.client.get(reverse('court_complex_detail', args=[self.physical.id]))

        self.assertEqual(response.status_code, 200)
        live = response.context['live_venue']
        self.assertTrue(live['is_physical'])
        self.assertEqual([entry.pk for entry in live['now_here']], [here.pk])
        self.assertEqual([entry.pk for entry in live['going']], [going.pk])
        self.assertEqual(live['community_report'].reported_count, 11)
        self.assertContains(response, 'Players at the courts')
        self.assertContains(response, 'When People Play')
        self.assertContains(response, f'/billboard/api/analytics/court/{self.physical.id}/')
        self.assertContains(response, 'venue-usage-hourly')
        self.assertContains(response, '~11')
        self.assertContains(response, 'Ioannina Court 1')
        self.assertNotContains(response, 'Other physical venue')

    def test_virtual_complex_does_not_receive_the_live_physical_venue_ui(self):
        BillboardEntry.objects.create(
            codename='VIRT01',
            action_type='AT_COURTS',
            court_complex=self.virtual,
            presence_source=BillboardEntry.PRESENCE_SOURCE_MANUAL,
        )

        response = self.client.get(reverse('court_complex_detail', args=[self.virtual.id]))

        self.assertEqual(response.status_code, 200)
        live = response.context['live_venue']
        self.assertFalse(live['is_physical'])
        self.assertEqual(live['now_here'], [])
        self.assertEqual(live['going'], [])
        self.assertContains(response, 'Live physical-presence information is available only')
        self.assertNotContains(response, 'Players at the courts')
        self.assertNotContains(response, 'When People Play')
