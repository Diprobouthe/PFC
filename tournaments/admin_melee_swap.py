"""
Admin action and view for safely swapping a Mêlée tournament participant.

WHAT THIS DOES
--------------
Allows an admin to replace Player A (who needs to leave) with Player B
(a registered PFC player who is NOT already in the tournament) while
keeping all existing match results, ratings, and leaderboard data intact.

SAFETY GUARANTEES
-----------------
1. Runs inside a single database transaction — if anything fails, nothing
   is changed.
2. Only works BEFORE teams are generated OR between rounds (never while a
   match is actively being played or awaiting validation — pending matches
   are allowed since PFC auto-generates next matches).
3. Validates that the incoming player is not already registered in the
   tournament.
4. Updates every table that references the departing player:
      • MeleePlayer          — the tournament registration record
      • Player.team          — live team assignment (if teams already generated)
      • MeleePlayerStats     — per-tournament stats row
      • MeleePartnership     — past-round partnership history
      • MeleeShuffleHistory  — not player-specific, no change needed
5. Does NOT touch completed Match records or PlayerProfile ratings —
   those belong to the departing player's history and must not be altered.
6. Refreshes the incoming player's session so they see the correct team
   immediately without logging out.
"""

import logging
from django import forms
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Form
# ---------------------------------------------------------------------------

class MeleeSwapForm(forms.Form):
    """Form shown to the admin when swapping a participant."""

    outgoing_player_id = forms.IntegerField(widget=forms.HiddenInput())
    tournament_id = forms.IntegerField(widget=forms.HiddenInput())

    incoming_player = forms.ModelChoiceField(
        queryset=None,  # set in __init__
        label="Replacement player",
        help_text=(
            "Select the player who will TAKE the spot. "
            "Only players who are NOT already registered in this tournament are shown."
        ),
        widget=forms.Select(attrs={"class": "select2", "style": "width:400px"}),
    )

    reason = forms.CharField(
        required=False,
        max_length=500,
        label="Reason / notes (optional)",
        widget=forms.Textarea(attrs={"rows": 2, "style": "width:400px"}),
    )

    def __init__(self, *args, tournament=None, outgoing_player=None, **kwargs):
        super().__init__(*args, **kwargs)
        from teams.models import Player
        from tournaments.models import MeleePlayer

        # Exclude players already registered in this tournament
        already_in = MeleePlayer.objects.filter(
            tournament=tournament
        ).values_list("player_id", flat=True)

        self.fields["incoming_player"].queryset = (
            Player.objects.exclude(id__in=already_in).order_by("name")
        )

        if outgoing_player:
            self.fields["outgoing_player_id"].initial = outgoing_player.pk
        if tournament:
            self.fields["tournament_id"].initial = tournament.pk


# ---------------------------------------------------------------------------
# Core swap logic
# ---------------------------------------------------------------------------

def perform_melee_swap(tournament, outgoing_player, incoming_player, admin_user, reason=""):
    """
    Atomically swap *outgoing_player* for *incoming_player* in *tournament*.

    Returns
    -------
    dict  {"success": bool, "message": str}
    """
    from tournaments.models import MeleePlayer
    from tournaments.partnership_models import MeleePlayerStats, MeleePartnership
    from pfc_core.session_refresh import refresh_player_team_session

    try:
        with transaction.atomic():

            # ── 1. Fetch the MeleePlayer registration record ──────────────
            try:
                melee_reg = MeleePlayer.objects.select_for_update().get(
                    tournament=tournament, player=outgoing_player
                )
            except MeleePlayer.DoesNotExist:
                return {
                    "success": False,
                    "message": (
                        f"{outgoing_player.name} is not registered in "
                        f"'{tournament.name}'."
                    ),
                }

            # ── 2. Guard: don't swap while a match is actively being played ─
            # "pending" matches are OK — PFC auto-generates next matches, so
            # there will almost always be pending matches between rounds.
            # Only truly in-progress statuses block the swap.
            if tournament.melee_teams_generated:
                from matches.models import Match
                active_matches = Match.objects.filter(
                    tournament=tournament,
                    status__in=["active", "waiting_validation"],
                )
                if active_matches.exists():
                    active_count = active_matches.count()
                    return {
                        "success": False,
                        "message": (
                            f"Cannot swap players while {active_count} match(es) "
                            f"are actively being played or awaiting validation. "
                            f"Wait for them to complete first."
                        ),
                    }

            # ── 3. Guard: incoming player not already registered ──────────
            if MeleePlayer.objects.filter(
                tournament=tournament, player=incoming_player
            ).exists():
                return {
                    "success": False,
                    "message": (
                        f"{incoming_player.name} is already registered in "
                        f"'{tournament.name}'."
                    ),
                }

            assigned_team = melee_reg.assigned_team
            original_team = melee_reg.original_team

            # ── 4. Update MeleePlayer registration ────────────────────────
            melee_reg.player = incoming_player
            # Keep assigned_team and original_team as-is so the incoming
            # player slots directly into the same team position.
            melee_reg.save()

            # ── 5. Transfer live team assignment (if teams generated) ──────
            if tournament.melee_teams_generated and assigned_team:
                # Move outgoing player back to their original team
                if original_team:
                    outgoing_player.team = original_team
                    outgoing_player.save()
                    # Outgoing player is restored → stop fast polling
                    refresh_player_team_session(outgoing_player, in_melee_assignment=False)
                    logger.info(
                        f"Restored {outgoing_player.name} → {original_team.name}"
                    )

                # Move incoming player to the mêlée team
                # Store their current team as the "original" so restoration works
                melee_reg.original_team = incoming_player.team
                melee_reg.save(update_fields=["original_team"])

                incoming_player.team = assigned_team
                incoming_player.save()
                # Incoming player is now in Mêlée → activate fast polling
                refresh_player_team_session(incoming_player, in_melee_assignment=True)
                logger.info(
                    f"Assigned {incoming_player.name} → {assigned_team.name}"
                )

            # ── 6. Migrate MeleePlayerStats ───────────────────────────────
            # If a stats row exists for the outgoing player, reassign it to
            # the incoming player (preserving wins/losses/points from rounds
            # already played — the incoming player inherits the slot's history).
            # If no stats row exists yet, nothing to do.
            stats_qs = MeleePlayerStats.objects.filter(
                tournament=tournament, player=outgoing_player
            )
            if stats_qs.exists():
                stats_qs.update(player=incoming_player)
                logger.info(
                    f"Migrated MeleePlayerStats from {outgoing_player.name} "
                    f"to {incoming_player.name}"
                )

            # ── 7. Migrate MeleePartnership history ───────────────────────
            # Partnerships record who played together in past rounds.
            # Reassign so the leaderboard correctly reflects the slot.
            updated_p1 = MeleePartnership.objects.filter(
                tournament=tournament, player1=outgoing_player
            ).update(player1=incoming_player)

            updated_p2 = MeleePartnership.objects.filter(
                tournament=tournament, player2=outgoing_player
            ).update(player2=incoming_player)

            logger.info(
                f"Updated {updated_p1 + updated_p2} MeleePartnership records "
                f"({outgoing_player.name} → {incoming_player.name})"
            )

            # ── 8. Log the swap ───────────────────────────────────────────
            logger.info(
                f"[MELEE SWAP] Tournament='{tournament.name}' | "
                f"OUT={outgoing_player.name} | IN={incoming_player.name} | "
                f"Admin={admin_user.username} | Reason='{reason}'"
            )

            return {
                "success": True,
                "message": (
                    f"Successfully swapped {outgoing_player.name} → "
                    f"{incoming_player.name} in '{tournament.name}'."
                    + (f" Reason: {reason}" if reason else "")
                ),
            }

    except Exception as exc:
        logger.exception(f"Melee swap failed: {exc}")
        return {"success": False, "message": f"Unexpected error: {exc}"}


# ---------------------------------------------------------------------------
# Admin view (mounted on MeleePlayerAdmin)
# ---------------------------------------------------------------------------

class MeleePlayerSwapAdminMixin:
    """
    Mixin for MeleePlayerAdmin that adds a per-row 'Swap Player' button
    and the corresponding confirmation view.
    """

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:melee_player_id>/swap/",
                self.admin_site.admin_view(self.swap_view),
                name="tournaments_meleeplayer_swap",
            ),
        ]
        return custom + urls

    # ── list_display helper ──────────────────────────────────────────────
    def swap_button(self, obj):
        url = reverse(
            "admin:tournaments_meleeplayer_swap",
            args=[obj.pk],
        )
        return format_html(
            '<a class="button" href="{}" style="'
            'background:#e67e22;color:#fff;padding:3px 8px;'
            'border-radius:4px;text-decoration:none;font-size:12px">'
            '🔄 Swap</a>',
            url,
        )

    swap_button.short_description = "Swap"
    swap_button.allow_tags = True

    # ── view ─────────────────────────────────────────────────────────────
    def swap_view(self, request, melee_player_id):
        from tournaments.models import MeleePlayer

        melee_player = get_object_or_404(MeleePlayer, pk=melee_player_id)
        tournament = melee_player.tournament
        outgoing = melee_player.player

        if request.method == "POST":
            form = MeleeSwapForm(
                request.POST,
                tournament=tournament,
                outgoing_player=outgoing,
            )
            if form.is_valid():
                incoming = form.cleaned_data["incoming_player"]
                reason = form.cleaned_data.get("reason", "")
                result = perform_melee_swap(
                    tournament=tournament,
                    outgoing_player=outgoing,
                    incoming_player=incoming,
                    admin_user=request.user,
                    reason=reason,
                )
                if result["success"]:
                    self.message_user(request, result["message"], messages.SUCCESS)
                else:
                    self.message_user(request, result["message"], messages.ERROR)
                return HttpResponseRedirect(
                    reverse("admin:tournaments_meleeplayer_changelist")
                    + f"?tournament__id__exact={tournament.pk}"
                )
        else:
            form = MeleeSwapForm(tournament=tournament, outgoing_player=outgoing)

        context = {
            **self.admin_site.each_context(request),
            "title": f"Swap Mêlée Participant — {outgoing.name}",
            "form": form,
            "tournament": tournament,
            "outgoing_player": outgoing,
            "melee_player": melee_player,
            "opts": self.model._meta,
        }
        return render(request, "admin/tournaments/meleeplayer/swap.html", context)
