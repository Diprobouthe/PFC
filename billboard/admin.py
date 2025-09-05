from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import BillboardEntry, BillboardResponse, BillboardSettings


@admin.register(BillboardEntry)
class BillboardEntryAdmin(admin.ModelAdmin):
    list_display = ('codename', 'action_type_display', 'court_complex', 'scheduled_time', 'response_count', 'status_badge', 'created_at')
    list_filter = ('action_type', 'court_complex', 'is_active', 'created_at')
    search_fields = ('codename', 'opponent_team', 'message')
    readonly_fields = ('created_at', 'updated_at', 'response_count')
    
    fieldsets = (
        ('Entry Information', {
            'fields': ('codename', 'action_type', 'court_complex')
        }),
        ('Details', {
            'fields': ('scheduled_time', 'opponent_team', 'message')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def action_type_display(self, obj):
        return obj.get_action_type_display()
    action_type_display.short_description = 'Action'
    
    def response_count(self, obj):
        count = obj.get_response_count()
        if count > 0:
            return format_html('<span style="color: #28a745; font-weight: bold;">{} responses</span>', count)
        return "No responses"
    response_count.short_description = 'Responses'
    
    def status_badge(self, obj):
        if not obj.is_active:
            return format_html('<span style="background-color: #dc3545; padding: 3px 8px; border-radius: 10px; color: #fff;">Inactive</span>')
        elif obj.is_expired():
            return format_html('<span style="background-color: #ffc107; padding: 3px 8px; border-radius: 10px; color: #000;">Expired</span>')
        else:
            return format_html('<span style="background-color: #28a745; padding: 3px 8px; border-radius: 10px; color: #fff;">Active</span>')
    status_badge.short_description = 'Status'
    
    actions = ['mark_as_inactive', 'mark_as_active']
    
    def mark_as_inactive(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f"{queryset.count()} entries marked as inactive.")
    mark_as_inactive.short_description = "Mark selected entries as inactive"
    
    def mark_as_active(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f"{queryset.count()} entries marked as active.")
    mark_as_active.short_description = "Mark selected entries as active"


@admin.register(BillboardResponse)
class BillboardResponseAdmin(admin.ModelAdmin):
    list_display = ('codename', 'entry_summary', 'response_type_display', 'created_at')
    list_filter = ('response_type', 'created_at', 'entry__action_type', 'entry__court_complex')
    search_fields = ('codename', 'entry__codename', 'entry__court_complex__name')
    readonly_fields = ('created_at',)
    
    fieldsets = (
        (None, {
            'fields': ('entry', 'codename', 'response_type')
        }),
        ('Timestamp', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    def entry_summary(self, obj):
        return f"{obj.entry.codename} - {obj.entry.get_action_type_display()}"
    entry_summary.short_description = 'Original Entry'
    
    def response_type_display(self, obj):
        return obj.get_response_type_display()
    response_type_display.short_description = 'Response'


@admin.register(BillboardSettings)
class BillboardSettingsAdmin(admin.ModelAdmin):
    list_display = ('max_entries_per_day', 'entry_expiry_hours', 'is_enabled')
    
    fieldsets = (
        ('Entry Limits', {
            'fields': ('max_entries_per_day', 'entry_expiry_hours')
        }),
        ('Module Control', {
            'fields': ('is_enabled',)
        }),
    )
    
    def has_add_permission(self, request):
        # Only allow one settings instance
        return not BillboardSettings.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        # Don't allow deletion of settings
        return False

