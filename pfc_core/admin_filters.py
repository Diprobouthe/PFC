"""
pfc_core/admin_filters.py
─────────────────────────
Shared Django admin mixins that ensure archived Teams and archived Tournaments
never appear in any admin dropdown, autocomplete, or selection widget.

Usage
-----
Inherit from the appropriate mixin(s) in any ModelAdmin that has FK/M2M
fields pointing at Team or Tournament:

    class MyAdmin(ActiveTeamMixin, ActiveTournamentMixin, admin.ModelAdmin):
        ...

The mixins override:
  • formfield_for_foreignkey  — standard <select> dropdowns
  • formfield_for_manytomany  — filter_horizontal / filter_vertical widgets
  • get_search_results        — autocomplete_fields queries

They do NOT touch the admin list view (so archived records remain accessible
through the list + filter panel).
"""

from django.contrib import admin


# ─────────────────────────────────────────────────────────────────────────────
# Team filtering
# ─────────────────────────────────────────────────────────────────────────────

class ActiveTeamMixin:
    """
    Exclude is_archived=True Teams from every FK/M2M/autocomplete widget
    in the admin form.
    """

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        from teams.models import Team
        if db_field.related_model is Team:
            kwargs['queryset'] = Team.objects.filter(is_archived=False)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        from teams.models import Team
        if db_field.related_model is Team:
            kwargs['queryset'] = Team.objects.filter(is_archived=False)
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def get_search_results(self, request, queryset, search_term):
        """Used by autocomplete_fields for Team."""
        from teams.models import Team
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        if queryset.model is Team:
            queryset = queryset.filter(is_archived=False)
        return queryset, use_distinct


# ─────────────────────────────────────────────────────────────────────────────
# Tournament filtering
# ─────────────────────────────────────────────────────────────────────────────

class ActiveTournamentMixin:
    """
    Exclude is_archived=True Tournaments from every FK/M2M/autocomplete widget
    in the admin form.
    """

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        from tournaments.models import Tournament
        if db_field.related_model is Tournament:
            kwargs['queryset'] = Tournament.objects.filter(is_archived=False)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        from tournaments.models import Tournament
        if db_field.related_model is Tournament:
            kwargs['queryset'] = Tournament.objects.filter(is_archived=False)
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def get_search_results(self, request, queryset, search_term):
        """Used by autocomplete_fields for Tournament."""
        from tournaments.models import Tournament
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        if queryset.model is Tournament:
            queryset = queryset.filter(is_archived=False)
        return queryset, use_distinct
