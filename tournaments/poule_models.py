"""
tournaments/poule_models.py
============================
Poule (Group) models for the PFC tournament system.

A Poule belongs to a Stage (which must have format="poule").
Each Poule has:
  - A name (e.g. "Group A", "Poule 1")
  - An ordered list of teams (through PouleTeam)
  - A set of courts (M2M) — matches within this poule use ONLY these courts

Design principles:
  - Additive: does not modify any existing model
  - Isolated: poule logic is contained here and in poule_admin.py / poule_views.py
  - Safe: all existing tournament types are completely unaffected
"""
import logging
from django.db import models

logger = logging.getLogger('tournaments')


class Poule(models.Model):
    """
    A group/poule within a Stage that has format='poule'.

    Teams are assigned via PouleTeam (ordered by position).
    Courts are assigned via a direct M2M to Court — matches in this
    poule will only use courts from this set.
    """
    stage = models.ForeignKey(
        'tournaments.Stage',
        on_delete=models.CASCADE,
        related_name='poules',
        help_text="The stage this poule belongs to (must have format='poule')"
    )
    name = models.CharField(
        max_length=100,
        help_text="Display name, e.g. 'Group A' or 'Poule 1'"
    )
    courts = models.ManyToManyField(
        'courts.Court',
        blank=True,
        related_name='poules',
        help_text="Courts assigned to this poule. Matches within this poule use ONLY these courts."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['stage', 'name']
        unique_together = [('stage', 'name')]
        verbose_name = 'Poule / Group'
        verbose_name_plural = 'Poules / Groups'

    def __str__(self):
        return f"{self.name} — {self.stage}"

    # ── Convenience helpers ──────────────────────────────────────────────────

    def get_teams(self):
        """Return Team queryset for this poule, ordered by position."""
        return [pt.team for pt in self.pouleteam_set.select_related('team').order_by('position')]

    def get_court_ids(self):
        """Return list of Court PKs assigned to this poule."""
        return list(self.courts.values_list('id', flat=True))

    def get_available_courts(self):
        """Return courts assigned to this poule that are currently available."""
        return self.courts.filter(is_available=True)

    def generate_matches(self):
        """
        Generate round-robin matches for all teams in this poule.
        Matches are created without a court assigned — the court is
        assigned at activation time from this poule's court pool.

        Returns the number of matches created.
        """
        from matches.models import Match
        from tournaments.models import Round

        teams = self.get_teams()
        if len(teams) < 2:
            logger.warning(f"[Poule] {self} has fewer than 2 teams — skipping match generation")
            return 0

        # Ensure the poule stage has a round
        round_obj, created = Round.objects.get_or_create(
            tournament=self.stage.tournament,
            stage=self.stage,
            number_in_stage=1,
            defaults={
                'number': self.stage._get_next_round_number(),
                'name': 'Round 1',
            }
        )
        if not created:
            # Clear only pending matches for this poule (identified by poule FK on match)
            Match.objects.filter(
                poule=self,
                status__in=['pending', 'scheduled']
            ).delete()

        matches_created = 0
        for i in range(len(teams)):
            for j in range(i + 1, len(teams)):
                Match.objects.create(
                    tournament=self.stage.tournament,
                    stage=self.stage,
                    round=round_obj,
                    poule=self,
                    team1=teams[i],
                    team2=teams[j],
                    status='pending',
                    time_limit_minutes=self.stage.tournament.default_time_limit_minutes,
                )
                matches_created += 1
                logger.debug(f"[Poule] Created match: {teams[i]} vs {teams[j]} in {self}")

        logger.info(f"[Poule] Generated {matches_created} matches for {self}")
        return matches_created

    def get_standings(self):
        """
        Return a list of dicts with per-team standings within this poule.
        Each dict: {team, played, won, lost, points, score_for, score_against, score_diff}
        Sorted by points desc, then score_diff desc.
        """
        from matches.models import Match

        teams = self.get_teams()
        stats = {
            t.id: {
                'team': t,
                'played': 0,
                'won': 0,
                'lost': 0,
                'points': 0,
                'score_for': 0,
                'score_against': 0,
            }
            for t in teams
        }

        matches = Match.objects.filter(
            poule=self,
            status='completed'
        ).select_related('team1', 'team2', 'winner')

        for m in matches:
            if m.team1_id not in stats or m.team2_id not in stats:
                continue
            s1 = stats[m.team1_id]
            s2 = stats[m.team2_id]
            s1['played'] += 1
            s2['played'] += 1

            # Score tracking (use score fields if available)
            score1 = getattr(m, 'team1_score', None) or 0
            score2 = getattr(m, 'team2_score', None) or 0
            s1['score_for'] += score1
            s1['score_against'] += score2
            s2['score_for'] += score2
            s2['score_against'] += score1

            if m.winner_id == m.team1_id:
                s1['won'] += 1
                s1['points'] += 2
                s2['lost'] += 1
            elif m.winner_id == m.team2_id:
                s2['won'] += 1
                s2['points'] += 2
                s1['lost'] += 1

        rows = list(stats.values())
        for r in rows:
            r['score_diff'] = r['score_for'] - r['score_against']
        rows.sort(key=lambda r: (-r['points'], -r['score_diff'], -r['score_for']))
        return rows


class PouleTeam(models.Model):
    """
    Through model: assigns a Team to a Poule with an optional seeding position.
    """
    poule = models.ForeignKey(
        Poule,
        on_delete=models.CASCADE,
        related_name='pouleteam_set'
    )
    team = models.ForeignKey(
        'teams.Team',
        on_delete=models.CASCADE,
        related_name='poule_assignments'
    )
    position = models.PositiveSmallIntegerField(
        default=0,
        help_text="Seeding position within the poule (lower = higher seed)"
    )

    class Meta:
        ordering = ['poule', 'position', 'team__name']
        unique_together = [('poule', 'team')]
        verbose_name = 'Poule Team Assignment'
        verbose_name_plural = 'Poule Team Assignments'

    def __str__(self):
        return f"{self.team.name} → {self.poule.name}"
