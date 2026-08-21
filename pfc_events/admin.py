from django.contrib import admin

from .models import WebPushSubscription


@admin.register(WebPushSubscription)
class WebPushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("player", "locale", "is_active", "last_success_at", "updated_at")
    list_filter = ("is_active", "locale")
    search_fields = ("player__name", "endpoint")
    readonly_fields = ("created_at", "updated_at", "last_success_at")
