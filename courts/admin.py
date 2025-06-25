from django.contrib import admin
from django.utils.html import format_html
from .models import Court, CourtComplex, CourtComplexRating, CourtComplexPhoto

@admin.register(Court)
class CourtAdmin(admin.ModelAdmin):
    list_display = ('number', 'name', 'get_complex_name', 'status_badge')
    list_filter = ('is_available',)
    search_fields = ('number', 'name')
    fieldsets = (
        (None, {
            'fields': ('number', 'name', 'location_description', 'is_available')
        }),
    )
    actions = ['mark_as_available', 'mark_as_occupied']
    
    def get_complex_name(self, obj):
        """Show which complex this court belongs to"""
        from .utils import get_court_complex_for_court
        complex_obj = get_court_complex_for_court(obj)
        if complex_obj:
            return complex_obj.name
        return "Not assigned"
    get_complex_name.short_description = "Court Complex"
    
    def status_badge(self, obj):
        if obj.is_available:
            return format_html('<span style="background-color: #28A745; padding: 3px 8px; border-radius: 10px; color: #fff;">Available</span>')
        else:
            return format_html('<span style="background-color: #DC3545; padding: 3px 8px; border-radius: 10px; color: #fff;">Occupied</span>')
    status_badge.short_description = "Status"
    
    def mark_as_available(self, request, queryset):
        queryset.update(is_available=True)
        self.message_user(request, f"{queryset.count()} courts marked as available.")
    mark_as_available.short_description = "Mark selected courts as available"
    
    def mark_as_occupied(self, request, queryset):
        queryset.update(is_available=False)
        self.message_user(request, f"{queryset.count()} courts marked as occupied.")
    mark_as_occupied.short_description = "Mark selected courts as occupied"

@admin.register(CourtComplex)
class CourtComplexAdmin(admin.ModelAdmin):
    list_display = ('name', 'get_court_count', 'get_court_numbers', 'public_accessibility', 'average_rating')
    list_filter = ('public_accessibility', 'has_shadow_daytime', 'has_night_lighting')
    search_fields = ('name', 'description')
    filter_horizontal = ('courts',)  # Nice interface for ManyToMany
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'courts')
        }),
        ('Facility Information', {
            'fields': ('distance_to_toilet', 'distance_to_water_hose', 'has_shadow_daytime', 'has_night_lighting', 'public_accessibility')
        }),
        ('Location & Contact', {
            'fields': ('google_maps_url', 'public_hours')
        }),
    )
    
    def get_court_count(self, obj):
        return obj.get_court_count()
    get_court_count.short_description = "Courts Count"
    
    def get_court_numbers(self, obj):
        numbers = obj.get_court_numbers()
        if numbers:
            return ", ".join(map(str, numbers))
        return "No courts assigned"
    get_court_numbers.short_description = "Court Numbers"

# Register other models that were already registered
@admin.register(CourtComplexRating)
class CourtComplexRatingAdmin(admin.ModelAdmin):
    list_display = ('court_complex', 'codename', 'stars', 'created_at')
    list_filter = ('stars', 'created_at')
    search_fields = ('court_complex__name', 'codename')

@admin.register(CourtComplexPhoto)
class CourtComplexPhotoAdmin(admin.ModelAdmin):
    list_display = ('court_complex', 'caption', 'uploaded_at')
    list_filter = ('uploaded_at',)
    search_fields = ('court_complex__name', 'caption')

