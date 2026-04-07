from django.contrib import admin
from django.conf import settings
from .models import PFCUser, EmailOTP


@admin.register(PFCUser)
class PFCUserAdmin(admin.ModelAdmin):
    list_display = ['email', 'provider', 'display_name', 'player_name', 'last_login', 'created_at', 'is_active']
    list_filter = ['provider', 'is_active', 'legacy_codename_linked']
    search_fields = ['email', 'display_name', 'player__name']
    readonly_fields = ['email', 'provider', 'google_sub', 'created_at', 'last_login', 'codename_display']
    raw_id_fields = ['player']

    fieldsets = (
        ('Identity', {
            'fields': ('email', 'provider', 'google_sub', 'display_name', 'avatar_url')
        }),
        ('PFC Link', {
            'fields': ('player', 'codename_display', 'legacy_codename_linked', 'legacy_link_skipped')
        }),
        ('Status', {
            'fields': ('is_active', 'last_login', 'created_at')
        }),
    )

    def player_name(self, obj):
        return obj.player.name if obj.player else '—'
    player_name.short_description = 'Player'

    def codename_display(self, obj):
        return obj.codename or '—'
    codename_display.short_description = 'Internal Codename (admin only)'


# ---------------------------------------------------------------------------
# TEMPORARY: Admin OTP Inspection
# Controlled by ENABLE_ADMIN_OTP_INSPECTION in settings.py.
# When the flag is False (or absent), this block is skipped entirely and
# EmailOTP is not registered in admin — no code is exposed anywhere.
# To remove permanently: delete this entire block and the flag from settings.
# ---------------------------------------------------------------------------
if getattr(settings, 'ENABLE_ADMIN_OTP_INSPECTION', False):

    @admin.register(EmailOTP)
    class EmailOTPAdmin(admin.ModelAdmin):
        """
        TEMPORARY admin view for OTP inspection during auth stabilisation.
        Visible only when ENABLE_ADMIN_OTP_INSPECTION = True in settings.
        Read-only. No login shortcuts. No bypass of normal OTP flow.
        """
        list_display = [
            'email',
            'code_display',
            'created_at',
            'expires_at',
            'status_display',
        ]
        list_filter = ['used']
        search_fields = ['email']
        readonly_fields = ['email', 'code', 'created_at', 'expires_at', 'used']
        ordering = ['-created_at']

        # Prevent any create/edit/delete from admin — inspection only
        def has_add_permission(self, request):
            return False

        def has_change_permission(self, request, obj=None):
            return False

        def has_delete_permission(self, request, obj=None):
            return False

        def code_display(self, obj):
            """Show OTP code only when inspection flag is active."""
            return obj.code
        code_display.short_description = '⚠ OTP Code (temp)'

        def status_display(self, obj):
            if obj.used:
                return '✓ Used'
            if not obj.is_valid():
                return '✗ Expired'
            return '⏳ Active'
        status_display.short_description = 'Status'
