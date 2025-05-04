from django.db import models

class Court(models.Model):
    number = models.IntegerField(unique=True)
    name = models.CharField(max_length=100, blank=True, help_text="Optional name for the court (e.g., Main Court)")
    location_description = models.TextField(blank=True, help_text="Description of the court's location")
    # picture = models.ImageField(upload_to='court_pictures/', blank=True, null=True, help_text="Optional picture of the court") # Add ImageField later if needed, requires Pillow
    is_active = models.BooleanField(default=False, help_text="If True, court is currently in use by a match")

    def __str__(self):
        return self.name if self.name else f"Court {self.number}"

    class Meta:
        ordering = ['number'] # Corrected syntax

