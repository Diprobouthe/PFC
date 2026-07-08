"""
tournaments/poule_admin.py
===========================
Django admin for Poule / Group management.

Admin workflow:
  1. Create a Tournament with format="multi_stage" (or any format that uses stages)
  2. Create a Stage with format="poule"
  3. In Poule admin: create poules for that stage, assign courts and teams
  4. Use the "Generate Poule Matches" action to create all round-robin matches

Admin UX improvements (admin-only, no public views changed):
  - Archived tournaments are excluded from the stage selector and list filters.
  - The stage selector is a searchable autocomplete widget.
  - The stage queryset is restricted to poule-format stages from non-archived tournaments.
  - PouleTeamInline team choices are scoped to teams registered in the poule's tournament.
  - The changelist tournament filter only shows non-archived tournaments.
"""
import logging
from django.contrib import admin
from django.utils.html import format_html
from django.contrib import messages

from .poule_models import Poule, PouleTeam
from pfc_core.admin_filters import ActiveTournamentMixin

logger = logging.getLogger('tournaments')


# ── Custom list filter: only non-archived tournaments ────────────────────────

class ActiveTournamentListFilter(admin.SimpleListFilter):
    """
    Replaces the default tournament list filter in the Poule changelist.
    Only shows tournaments that are not archived, keeping the filter panel clean.
    """
    title = 'Tournament'
    parameter_name = 'tournament'

    def lookups(self, request, model_admin):
        from tournaments.models import Tournament
        qs = Tournament.objects.filter(
            is_archived=False,
            stages__poules__isnull=False,
        ).distinct().order_by('-start_date', 'name')
        return [(t.pk, t.name) for t in qs]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(stage__tournament_id=self.value())
        return queryset


class ActiveStageListFilter(admin.SimpleListFilter):
    """
    Stage list filter scoped to non-archived tournaments.
    """
    title = 'Stage'
    parameter_name = 'stage'

    def lookups(self, request, model_admin):
        from tournaments.models import Stage
        qs = Stage.objects.filter(
            tournament__is_archived=False,
            format='poule',
            poules__isnull=False,
        ).select_related('tournament').distinct().order_by(
            '-tournament__start_date', 'tournament__name', 'stage_number'
        )
        return [(s.pk, str(s)) for s in qs]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(stage_id=self.value())
        return queryset


# ── Inline: team assignments inside a Poule ──────────────────────────────────

class PouleTeamInline(admin.TabularInline):
    model = PouleTeam
    extra = 3
    fields = ('team', 'position')
    autocomplete_fields = ['team']
    ordering = ('position', 'team__name')
    verbose_name = "Team in this Poule"
    verbose_name_plural = "Teams in this Poule"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """
        Scope the team dropdown to teams registered in the poule's tournament.
        Falls back to all non-archived teams if the poule is new (no pk yet).
        """
        if db_field.name == 'team':
            from teams.models import Team
            from tournaments.models import TournamentTeam

            # Try to resolve the parent poule from the URL
            poule_id = request.resolver_match.kwargs.get('object_id')
            if poule_id:
                try:
                    poule = Poule.objects.select_related('stage__tournament').get(pk=poule_id)
                    tournament = poule.stage.tournament
                    registered_team_ids = TournamentTeam.objects.filter(
                        tournament=tournament,
                    ).values_list('team_id', flat=True)
                    kwargs['queryset'] = Team.objects.filter(
                        pk__in=registered_team_ids,
                        is_archived=False,
                    ).order_by('name')
                except Poule.DoesNotExist:
                    kwargs['queryset'] = Team.objects.filter(is_archived=False).order_by('name')
            else:
                # New poule — show all non-archived teams
                kwargs['queryset'] = Team.objects.filter(is_archived=False).order_by('name')

        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# ── Main Poule admin ─────────────────────────────────────────────────────────

@admin.register(Poule)
class PouleAdmin(ActiveTournamentMixin, admin.ModelAdmin):
    list_display = (
        'name',
        'stage_link',
        'tournament_link',
        'team_count',
        'court_list',
        'match_count',
        'generate_button',
    )
    # Use custom filters that exclude archived tournaments
    list_filter = (ActiveTournamentListFilter, ActiveStageListFilter)
    search_fields = ('name', 'stage__tournament__name', 'stage__name')
    ordering = ('stage__tournament', 'stage__stage_number', 'name')
    filter_horizontal = ('courts',)
    inlines = [PouleTeamInline]

    # Use autocomplete for stage — makes it a searchable widget
    autocomplete_fields = ['stage']

    fieldsets = (
        (None, {
            'fields': ('stage', 'name'),
            'description': (
                '<strong>Step 1:</strong> Search and select the Stage '
                '(must have format = "Poules/Groups"). '
                'Only active (non-archived) tournaments are shown. '
                'Give the poule a name, e.g. "Group A".'
            ),
        }),
        ('Court Assignment', {
            'fields': ('courts',),
            'description': (
                '<strong>Step 2:</strong> Assign courts to this poule. '
                'Matches within this poule will ONLY use these courts when activated.'
            ),
        }),
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """
        Restrict the stage FK to poule-format stages from non-archived tournaments.
        This applies to the standard <select> fallback; autocomplete_fields uses
        StageAdmin.get_search_results instead.
        """
        if db_field.name == 'stage':
            from tournaments.models import Stage
            kwargs['queryset'] = Stage.objects.filter(
                format='poule',
                tournament__is_archived=False,
            ).select_related('tournament').order_by(
                '-tournament__start_date', 'tournament__name', 'stage_number'
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # ── Custom column helpers ────────────────────────────────────────────────

    def stage_link(self, obj):
        return format_html(
            '<a href="/admin/tournaments/stage/{}/change/">{}</a>',
            obj.stage_id,
            str(obj.stage),
        )
    stage_link.short_description = 'Stage'
    stage_link.admin_order_field = 'stage__stage_number'

    def tournament_link(self, obj):
        t = obj.stage.tournament
        return format_html(
            '<a href="/admin/tournaments/tournament/{}/change/">{}</a>',
            t.pk,
            t.name,
        )
    tournament_link.short_description = 'Tournament'
    tournament_link.admin_order_field = 'stage__tournament__name'

    def team_count(self, obj):
        n = obj.pouleteam_set.count()
        return format_html('<strong>{}</strong> team{}', n, 's' if n != 1 else '')
    team_count.short_description = 'Teams'

    def court_list(self, obj):
        courts = obj.courts.order_by('number')
        if not courts.exists():
            return format_html('<span style="color:#e53e3e">⚠ No courts assigned</span>')
        labels = ', '.join(f'Court {c.number}' for c in courts)
        return format_html('<span style="color:#2f855a">✓ {}</span>', labels)
    court_list.short_description = 'Courts'

    def match_count(self, obj):
        from matches.models import Match
        n = Match.objects.filter(poule=obj).count()
        pending = Match.objects.filter(poule=obj, status='pending').count()
        completed = Match.objects.filter(poule=obj, status='completed').count()
        if n == 0:
            return format_html('<span style="color:#718096">No matches yet</span>')
        return format_html(
            '{} total ({} pending, {} done)',
            n, pending, completed,
        )
    match_count.short_description = 'Matches'

    def generate_button(self, obj):
        return format_html(
            '<a class="button" href="/admin/tournaments/poule/{}/generate_matches/" '
            'style="background:#2b6cb0;color:#fff;padding:3px 8px;border-radius:4px;'
            'text-decoration:none;font-size:12px">Generate Matches</a>',
            obj.pk,
        )
    generate_button.short_description = 'Action'
    generate_button.allow_tags = True

    # ── Custom URL for per-poule match generation ────────────────────────────

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom = [
            path(
                '<int:poule_id>/generate_matches/',
                self.admin_site.admin_view(self.generate_matches_view),
                name='poule_generate_matches',
            ),
        ]
        return custom + urls

    def generate_matches_view(self, request, poule_id):
        from django.shortcuts import redirect, get_object_or_404
        poule = get_object_or_404(Poule, pk=poule_id)

        # Validate: stage must be poule format
        if poule.stage.format != 'poule':
            self.message_user(
                request,
                f'Stage "{poule.stage}" is not a poule-format stage (format={poule.stage.format}). '
                'Cannot generate poule matches.',
                level=messages.ERROR,
            )
            return redirect('admin:tournaments_poule_changelist')

        # Validate: courts assigned
        if not poule.courts.exists():
            self.message_user(
                request,
                f'Poule "{poule.name}" has no courts assigned. '
                'Please assign courts before generating matches.',
                level=messages.WARNING,
            )
            return redirect('admin:tournaments_poule_changelist')

        # Validate: teams assigned
        team_count = poule.pouleteam_set.count()
        if team_count < 2:
            self.message_user(
                request,
                f'Poule "{poule.name}" has only {team_count} team(s). '
                'At least 2 teams are required.',
                level=messages.WARNING,
            )
            return redirect('admin:tournaments_poule_changelist')

        try:
            n = poule.generate_matches()
            self.message_user(
                request,
                f'✅ Generated {n} match(es) for poule "{poule.name}".',
            )
        except Exception as exc:
            logger.exception(f'Error generating matches for poule {poule_id}: {exc}')
            self.message_user(
                request,
                f'❌ Error generating matches: {exc}',
                level=messages.ERROR,
            )

        return redirect('admin:tournaments_poule_changelist')

    # ── Bulk action: generate matches for all selected poules ────────────────

    actions = ['bulk_generate_matches']

    @admin.action(description='Generate round-robin matches for selected poules')
    def bulk_generate_matches(self, request, queryset):
        total = 0
        errors = []
        for poule in queryset:
            if poule.stage.format != 'poule':
                errors.append(f'{poule}: stage is not poule format')
                continue
            if not poule.courts.exists():
                errors.append(f'{poule}: no courts assigned')
                continue
            if poule.pouleteam_set.count() < 2:
                errors.append(f'{poule}: fewer than 2 teams')
                continue
            try:
                n = poule.generate_matches()
                total += n
            except Exception as exc:
                errors.append(f'{poule}: {exc}')

        if total:
            self.message_user(request, f'✅ Generated {total} match(es) across {queryset.count()} poule(s).')
        for err in errors:
            self.message_user(request, f'⚠ {err}', level=messages.WARNING)
