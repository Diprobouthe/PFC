"""
tournaments/poule_admin.py
===========================
Django admin for Poule / Group management.

Admin workflow:
  1. Create a Tournament with format="multi_stage" (or any format that uses stages)
  2. Create a Stage with format="poule"
  3. In Poule admin: create poules for that stage, assign courts and teams
  4. Use the "Generate Poule Matches" action to create all round-robin matches
"""
import logging
from django.contrib import admin
from django.utils.html import format_html
from django.contrib import messages

from .poule_models import Poule, PouleTeam

logger = logging.getLogger('tournaments')


# ── Inline: team assignments inside a Poule ──────────────────────────────────

class PouleTeamInline(admin.TabularInline):
    model = PouleTeam
    extra = 3
    fields = ('team', 'position')
    autocomplete_fields = ['team']
    ordering = ('position', 'team__name')
    verbose_name = "Team in this Poule"
    verbose_name_plural = "Teams in this Poule"


# ── Main Poule admin ─────────────────────────────────────────────────────────

@admin.register(Poule)
class PouleAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'stage_link',
        'tournament_link',
        'team_count',
        'court_list',
        'match_count',
        'generate_button',
    )
    list_filter = ('stage__tournament', 'stage')
    search_fields = ('name', 'stage__tournament__name', 'stage__name')
    ordering = ('stage__tournament', 'stage__stage_number', 'name')
    filter_horizontal = ('courts',)
    inlines = [PouleTeamInline]

    fieldsets = (
        (None, {
            'fields': ('stage', 'name'),
            'description': (
                '<strong>Step 1:</strong> Select the Stage (must have format = "Poules/Groups"). '
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
