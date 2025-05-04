from django.contrib import admin
from django.utils.html import format_html
from .models import Court

@admin.register(Court)
class CourtAdmin(admin.ModelAdmin):
    list_display = ('number', 'status_badge')
    list_filter = ('is_active',)
    search_fields = ('number',)
    fieldsets = (
        (None, {
            'fields': ('number', 'is_active')
        }),
    )
    actions = ['mark_as_active', 'mark_as_inactive']
    
    def status_badge(self, obj):
        if obj.is_active:
            return format_html('<span style="background-color: #28A745; padding: 3px 8px; border-radius: 10px; color: #fff;">Active</span>')
        else:
            return format_html('<span style="background-color: #DC3545; padding: 3px 8px; border-radius: 10px; color: #fff;">Inactive</span>')
    status_badge.short_description = "Status"
    
    def mark_as_active(self, request, queryset):
        queryset.update(is_active=True)
    mark_as_active.short_description = "Mark selected courts as active"
    
    def mark_as_inactive(self, request, queryset):
        queryset.update(is_active=False)
    mark_as_inactive.short_description = "Mark selected courts as inactive"
