from django.db import models

class Court(models.Model):
    number = models.IntegerField(unique=True)
    name = models.CharField(max_length=100, blank=True, help_text="Optional name for the court (e.g., Main Court)")
    location_description = models.TextField(blank=True, help_text="Description of the court's location")
    # picture = models.ImageField(upload_to='court_pictures/', blank=True, null=True, help_text="Optional picture of the court") # Add ImageField later if needed, requires Pillow
    is_available = models.BooleanField(default=True, help_text="If True, court is available for use. If False, court is occupied by a match")

    def __str__(self):
        return self.name if self.name else f"Court {self.number}"

    class Meta:
        ordering = ['number'] # Corrected syntax



class CourtComplex(models.Model):
    """
    A CourtComplex groups multiple courts together and provides
    facility metadata and environmental information.
    """
    name = models.CharField(max_length=200, help_text="Name of the court complex")
    description = models.TextField(help_text="Detailed description of the complex")
    
    # Court assignment - ManyToMany relationship to courts
    courts = models.ManyToManyField(
        'Court',
        blank=True,
        help_text="Courts assigned to this complex"
    )
    
    # Facility information
    distance_to_toilet = models.IntegerField(
        help_text="Distance to nearest toilet in meters", 
        null=True, blank=True
    )
    distance_to_water_hose = models.IntegerField(
        help_text="Distance to water hose in meters", 
        null=True, blank=True
    )
    has_shadow_daytime = models.BooleanField(
        default=False, 
        help_text="Whether the complex has natural shade during daytime"
    )
    has_night_lighting = models.BooleanField(
        default=False, 
        help_text="Whether the complex has lighting for night play"
    )
    public_accessibility = models.IntegerField(
        choices=[(i, f"{i} star{'s' if i != 1 else ''}") for i in range(1, 6)],
        default=3,
        help_text="Public accessibility rating (1-5 scale)"
    )
    
    # Map and contact info
    google_maps_url = models.URLField(blank=True, help_text="Google Maps link")
    public_hours = models.TextField(
        blank=True, 
        help_text="Public access hours (e.g., 'Mon-Fri: 09:00-22:00')"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.name
    
    def average_rating(self):
        """Calculate average user rating"""
        ratings = self.ratings.all()
        if not ratings:
            return 0
        return sum(rating.stars for rating in ratings) / len(ratings)
    
    def rating_count(self):
        """Get total number of ratings"""
        return self.ratings.count()
    
    def get_court_numbers(self):
        """Get list of court numbers assigned to this complex"""
        return list(self.courts.values_list('number', flat=True).order_by('number'))
    
    def get_court_count(self):
        """Get count of courts assigned to this complex"""
        return self.courts.count()
    
    class Meta:
        ordering = ['name']


class CourtComplexRating(models.Model):
    """
    User ratings for court complexes with codenames for privacy
    """
    court_complex = models.ForeignKey(
        CourtComplex, 
        on_delete=models.CASCADE, 
        related_name='ratings'
    )
    codename = models.CharField(
        max_length=50, 
        help_text="User's codename for privacy"
    )
    stars = models.FloatField(
        choices=[(i*0.5, f"{i*0.5} stars") for i in range(1, 11)],  # 0.5 to 5.0 in 0.5 increments
        help_text="Rating from 0.5 to 5.0 stars"
    )
    comment = models.TextField(
        blank=True, 
        help_text="Optional comment about the complex"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.codename}: {self.stars} stars for {self.court_complex.name}"
    
    class Meta:
        ordering = ['-created_at']
        unique_together = ['court_complex', 'codename']  # One rating per codename per complex


class CourtComplexPhoto(models.Model):
    """
    Photos for court complexes (up to 4 per complex)
    """
    court_complex = models.ForeignKey(
        CourtComplex, 
        on_delete=models.CASCADE, 
        related_name='photos'
    )
    image = models.ImageField(
        upload_to='court_complex_photos/', 
        help_text="Photo of the court complex"
    )
    caption = models.CharField(
        max_length=200, 
        blank=True, 
        help_text="Optional caption for the photo"
    )
    is_cover = models.BooleanField(
        default=False, 
        help_text="Whether this is the cover photo"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Photo for {self.court_complex.name}"
    
    class Meta:
        ordering = ['-is_cover', 'uploaded_at']

