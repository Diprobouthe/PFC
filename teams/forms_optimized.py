# Django Forms with Image Optimization

from django import forms
from django.core.exceptions import ValidationError
from .models import PlayerProfile, TeamProfile
from .image_utils import validate_image_size, get_image_info

class OptimizedImageWidget(forms.ClearableFileInput):
    """Enhanced file input widget with client-side optimization support"""
    
    template_name = 'widgets/optimized_image_input.html'
    
    def __init__(self, attrs=None, image_type='general'):
        default_attrs = {
            'class': 'form-control-file optimized-image-input',
            'data-image-type': image_type,
            'accept': 'image/*'
        }
        if attrs:
            default_attrs.update(attrs)
        super().__init__(default_attrs)

class PlayerProfileForm(forms.ModelForm):
    """Enhanced PlayerProfile form with image optimization"""
    
    class Meta:
        model = PlayerProfile
        fields = ['profile_picture', 'bio', 'preferred_position', 'skill_level']
        widgets = {
            'profile_picture': OptimizedImageWidget(
                attrs={
                    'data-max-size': '3',  # 3MB
                    'data-max-width': '300',
                    'data-max-height': '300',
                },
                image_type='profile'
            ),
            'bio': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'preferred_position': forms.Select(attrs={'class': 'form-control'}),
            'skill_level': forms.Select(attrs={'class': 'form-control'}),
        }
    
    def clean_profile_picture(self):
        """Validate profile picture upload"""
        picture = self.cleaned_data.get('profile_picture')
        
        if picture:
            # Validate file size (3MB limit)
            if not validate_image_size(picture, max_size_mb=3):
                raise ValidationError("Profile picture must be smaller than 3MB")
            
            # Get image info for additional validation
            info = get_image_info(picture)
            if 'error' in info:
                raise ValidationError("Invalid image file")
            
            # Validate dimensions (optional - will be resized anyway)
            if info.get('width', 0) > 2000 or info.get('height', 0) > 2000:
                raise ValidationError("Image dimensions too large (max 2000x2000)")
        
        return picture

class TeamProfileForm(forms.ModelForm):
    """Enhanced TeamProfile form with image optimization"""
    
    class Meta:
        model = TeamProfile
        fields = ['logo_svg', 'team_photo_jpg', 'motto', 'description']
        widgets = {
            'logo_svg': OptimizedImageWidget(
                attrs={
                    'data-max-size': '2',  # 2MB
                    'data-max-width': '400',
                    'data-max-height': '400',
                    'accept': 'image/*,.svg',
                },
                image_type='logo'
            ),
            'team_photo_jpg': OptimizedImageWidget(
                attrs={
                    'data-max-size': '5',  # 5MB
                    'data-max-width': '1200',
                    'data-max-height': '800',
                },
                image_type='photo'
            ),
            'motto': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 200}),
            'description': forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
        }
    
    def clean_logo_svg(self):
        """Validate team logo upload"""
        logo = self.cleaned_data.get('logo_svg')
        
        if logo:
            # For SVG files, check file size only
            if logo.name.lower().endswith('.svg'):
                if logo.size > 1024 * 1024:  # 1MB for SVG
                    raise ValidationError("SVG logo must be smaller than 1MB")
            else:
                # For other formats, use standard validation
                if not validate_image_size(logo, max_size_mb=2):
                    raise ValidationError("Logo must be smaller than 2MB")
                
                info = get_image_info(logo)
                if 'error' in info:
                    raise ValidationError("Invalid image file")
        
        return logo
    
    def clean_team_photo_jpg(self):
        """Validate team photo upload"""
        photo = self.cleaned_data.get('team_photo_jpg')
        
        if photo:
            # Validate file size (5MB limit)
            if not validate_image_size(photo, max_size_mb=5):
                raise ValidationError("Team photo must be smaller than 5MB")
            
            # Get image info for additional validation
            info = get_image_info(photo)
            if 'error' in info:
                raise ValidationError("Invalid image file")
            
            # Validate dimensions
            if info.get('width', 0) > 3000 or info.get('height', 0) > 3000:
                raise ValidationError("Image dimensions too large (max 3000x3000)")
        
        return photo

# Utility function for AJAX image validation
def validate_image_ajax(request):
    """AJAX endpoint for client-side image validation"""
    if request.method == 'POST' and request.FILES.get('image'):
        image = request.FILES['image']
        image_type = request.POST.get('type', 'general')
        
        try:
            # Validate based on type
            if image_type == 'profile':
                if not validate_image_size(image, max_size_mb=3):
                    return JsonResponse({'valid': False, 'error': 'File too large (max 3MB)'})
            elif image_type == 'logo':
                if image.name.lower().endswith('.svg'):
                    if image.size > 1024 * 1024:
                        return JsonResponse({'valid': False, 'error': 'SVG too large (max 1MB)'})
                else:
                    if not validate_image_size(image, max_size_mb=2):
                        return JsonResponse({'valid': False, 'error': 'File too large (max 2MB)'})
            elif image_type == 'photo':
                if not validate_image_size(image, max_size_mb=5):
                    return JsonResponse({'valid': False, 'error': 'File too large (max 5MB)'})
            
            # Get image info
            info = get_image_info(image)
            if 'error' in info:
                return JsonResponse({'valid': False, 'error': 'Invalid image file'})
            
            return JsonResponse({
                'valid': True,
                'info': info,
                'optimized': True
            })
            
        except Exception as e:
            return JsonResponse({'valid': False, 'error': str(e)})
    
    return JsonResponse({'valid': False, 'error': 'No image provided'})

