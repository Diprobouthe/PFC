// Image Upload Optimization - Client-Side JavaScript
// Add this to your base template or team management forms

class ImageOptimizer {
    constructor(options = {}) {
        this.maxWidth = options.maxWidth || 1200;
        this.maxHeight = options.maxHeight || 800;
        this.quality = options.quality || 0.85;
        this.maxSizeMB = options.maxSizeMB || 5;
    }

    // Compress and resize image on client side
    async optimizeImage(file) {
        return new Promise((resolve, reject) => {
            // Check file size first
            if (file.size > this.maxSizeMB * 1024 * 1024) {
                reject(new Error(`File size must be less than ${this.maxSizeMB}MB`));
                return;
            }

            // Check file type
            if (!file.type.startsWith('image/')) {
                reject(new Error('File must be an image'));
                return;
            }

            // For SVG files, don't compress
            if (file.type === 'image/svg+xml') {
                resolve(file);
                return;
            }

            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');
            const img = new Image();

            img.onload = () => {
                // Calculate new dimensions
                let { width, height } = this.calculateDimensions(img.width, img.height);
                
                // Set canvas size
                canvas.width = width;
                canvas.height = height;

                // Draw and compress image
                ctx.drawImage(img, 0, 0, width, height);

                // Convert to blob
                canvas.toBlob((blob) => {
                    if (blob) {
                        // Create new file with optimized data
                        const optimizedFile = new File([blob], file.name, {
                            type: 'image/jpeg',
                            lastModified: Date.now()
                        });
                        resolve(optimizedFile);
                    } else {
                        reject(new Error('Failed to optimize image'));
                    }
                }, 'image/jpeg', this.quality);
            };

            img.onerror = () => reject(new Error('Failed to load image'));
            img.src = URL.createObjectURL(file);
        });
    }

    calculateDimensions(originalWidth, originalHeight) {
        let width = originalWidth;
        let height = originalHeight;

        // Scale down if too large
        if (width > this.maxWidth || height > this.maxHeight) {
            const widthRatio = this.maxWidth / width;
            const heightRatio = this.maxHeight / height;
            const scale = Math.min(widthRatio, heightRatio);

            width = Math.round(width * scale);
            height = Math.round(height * scale);
        }

        return { width, height };
    }

    // Show image preview with size info
    showPreview(file, previewElement) {
        const reader = new FileReader();
        reader.onload = (e) => {
            const img = document.createElement('img');
            img.src = e.target.result;
            img.style.maxWidth = '200px';
            img.style.maxHeight = '200px';
            img.style.objectFit = 'cover';
            
            const sizeInfo = document.createElement('div');
            sizeInfo.innerHTML = `
                <small class="text-muted">
                    Size: ${(file.size / 1024 / 1024).toFixed(2)} MB<br>
                    Type: ${file.type}
                </small>
            `;
            
            previewElement.innerHTML = '';
            previewElement.appendChild(img);
            previewElement.appendChild(sizeInfo);
        };
        reader.readAsDataURL(file);
    }
}

// Initialize optimizers for different image types
const profilePictureOptimizer = new ImageOptimizer({
    maxWidth: 300,
    maxHeight: 300,
    quality: 0.9,
    maxSizeMB: 3
});

const teamLogoOptimizer = new ImageOptimizer({
    maxWidth: 400,
    maxHeight: 400,
    quality: 0.95,
    maxSizeMB: 2
});

const teamPhotoOptimizer = new ImageOptimizer({
    maxWidth: 1200,
    maxHeight: 800,
    quality: 0.85,
    maxSizeMB: 5
});

// Enhanced file input handler
function setupImageOptimization() {
    // Profile picture optimization
    const profileInput = document.querySelector('input[name="profile_picture"]');
    if (profileInput) {
        setupFileInput(profileInput, profilePictureOptimizer, 'profile-preview');
    }

    // Team logo optimization
    const logoInput = document.querySelector('input[name="logo_svg"]');
    if (logoInput) {
        setupFileInput(logoInput, teamLogoOptimizer, 'logo-preview');
    }

    // Team photo optimization
    const photoInput = document.querySelector('input[name="team_photo_jpg"]');
    if (photoInput) {
        setupFileInput(photoInput, teamPhotoOptimizer, 'photo-preview');
    }
}

function setupFileInput(input, optimizer, previewId) {
    const previewElement = document.getElementById(previewId) || createPreviewElement(input, previewId);
    
    input.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        try {
            // Show loading state
            previewElement.innerHTML = '<div class="spinner-border spinner-border-sm" role="status"></div> Optimizing...';
            
            // Show original preview
            optimizer.showPreview(file, previewElement);
            
            // Optimize image
            const optimizedFile = await optimizer.optimizeImage(file);
            
            // Replace file input with optimized version
            const dt = new DataTransfer();
            dt.items.add(optimizedFile);
            input.files = dt.files;
            
            // Update preview with optimization info
            const optimizationInfo = document.createElement('div');
            optimizationInfo.innerHTML = `
                <small class="text-success">
                    ✓ Optimized: ${(optimizedFile.size / 1024 / 1024).toFixed(2)} MB
                    (${((1 - optimizedFile.size / file.size) * 100).toFixed(1)}% smaller)
                </small>
            `;
            previewElement.appendChild(optimizationInfo);
            
        } catch (error) {
            previewElement.innerHTML = `<small class="text-danger">Error: ${error.message}</small>`;
        }
    });
}

function createPreviewElement(input, previewId) {
    const preview = document.createElement('div');
    preview.id = previewId;
    preview.className = 'mt-2 p-2 border rounded';
    input.parentNode.appendChild(preview);
    return preview;
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', setupImageOptimization);

// Progress bar for large uploads
function showUploadProgress(input) {
    const form = input.closest('form');
    if (!form) return;

    form.addEventListener('submit', (e) => {
        const progressContainer = document.createElement('div');
        progressContainer.innerHTML = `
            <div class="progress mt-3">
                <div class="progress-bar progress-bar-striped progress-bar-animated" 
                     role="progressbar" style="width: 0%"></div>
            </div>
            <small class="text-muted">Uploading images...</small>
        `;
        
        form.appendChild(progressContainer);
        
        // Simulate progress (in real implementation, use XMLHttpRequest for actual progress)
        let progress = 0;
        const interval = setInterval(() => {
            progress += Math.random() * 30;
            if (progress >= 100) {
                progress = 100;
                clearInterval(interval);
            }
            progressContainer.querySelector('.progress-bar').style.width = progress + '%';
        }, 200);
    });
}

