from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from PIL import Image
import io
import os

def optimize_image(image_file, max_width=800, max_height=600, quality=85, format_override=None):
    """
    Optimize uploaded images by resizing and compressing them.
    
    Args:
        image_file: Django UploadedFile object
        max_width: Maximum width in pixels
        max_height: Maximum height in pixels  
        quality: JPEG quality (1-100)
        format_override: Force specific format ('JPEG', 'PNG', 'WEBP')
    
    Returns:
        ContentFile: Optimized image as Django ContentFile
    """
    try:
        # Open the image
        image = Image.open(image_file)
        
        # Convert RGBA to RGB for JPEG compatibility
        if image.mode in ('RGBA', 'LA', 'P'):
            # Create white background for transparency
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
            image = background
        
        # Get original dimensions
        original_width, original_height = image.size
        
        # Calculate new dimensions while maintaining aspect ratio
        if original_width > max_width or original_height > max_height:
            # Calculate scaling factor
            width_ratio = max_width / original_width
            height_ratio = max_height / original_height
            scale_factor = min(width_ratio, height_ratio)
            
            new_width = int(original_width * scale_factor)
            new_height = int(original_height * scale_factor)
            
            # Resize image with high-quality resampling
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Determine output format
        if format_override:
            output_format = format_override
        elif image_file.name.lower().endswith(('.png', '.gif')):
            output_format = 'PNG'
        else:
            output_format = 'JPEG'
        
        # Save optimized image to memory
        output_buffer = io.BytesIO()
        
        if output_format == 'JPEG':
            image.save(output_buffer, format='JPEG', quality=quality, optimize=True)
        elif output_format == 'PNG':
            image.save(output_buffer, format='PNG', optimize=True)
        elif output_format == 'WEBP':
            image.save(output_buffer, format='WEBP', quality=quality, optimize=True)
        
        output_buffer.seek(0)
        
        # PRESERVE ORIGINAL FILENAME - this is crucial for display
        original_name = image_file.name
        
        return ContentFile(output_buffer.getvalue(), name=original_name)
        
    except Exception as e:
        print(f"Image optimization failed: {e}")
        # Return original file if optimization fails
        return image_file

def optimize_profile_picture(image_file):
    """Optimize player profile pictures (smaller, square-ish)"""
    return optimize_image(
        image_file, 
        max_width=300, 
        max_height=300, 
        quality=90,
        format_override='JPEG'
    )

def optimize_team_logo(image_file):
    """Optimize team logos (medium size, preserve quality)"""
    # For SVG files, don't optimize (keep vector format)
    if image_file.name.lower().endswith('.svg'):
        return image_file
    
    return optimize_image(
        image_file, 
        max_width=400, 
        max_height=400, 
        quality=95,
        format_override='PNG'  # Preserve transparency for logos
    )

def optimize_team_photo(image_file):
    """Optimize team photos (larger, good quality)"""
    return optimize_image(
        image_file, 
        max_width=1200, 
        max_height=800, 
        quality=85,
        format_override='JPEG'
    )

def validate_image_size(image_file, max_size_mb=5):
    """
    Validate image file size before processing.
    
    Args:
        image_file: Django UploadedFile object
        max_size_mb: Maximum file size in megabytes
    
    Returns:
        bool: True if file size is acceptable
    """
    max_size_bytes = max_size_mb * 1024 * 1024
    return image_file.size <= max_size_bytes

def get_image_info(image_file):
    """
    Get information about an uploaded image.
    
    Returns:
        dict: Image information (dimensions, format, size)
    """
    try:
        image = Image.open(image_file)
        return {
            'width': image.width,
            'height': image.height,
            'format': image.format,
            'mode': image.mode,
            'size_bytes': image_file.size,
            'size_mb': round(image_file.size / (1024 * 1024), 2)
        }
    except Exception as e:
        return {'error': str(e)}

