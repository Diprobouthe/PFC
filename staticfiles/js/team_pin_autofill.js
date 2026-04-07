// Simple Team PIN Auto-Fill System
// This script provides auto-fill functionality for team PINs across the platform

(function() {
    'use strict';
    
    // Configuration
    const STORAGE_KEY = 'pfc_team_pin';
    const PIN_FIELD_SELECTORS = [
        'input[placeholder*="*"]',  // PIN fields with asterisk placeholders
        'input[name*="pin"]',       // Fields with "pin" in name
        'input[id*="pin"]',         // Fields with "pin" in ID
        '.team-pin-field'           // Fields with team-pin-field class
    ];
    
    // Team PIN Manager
    const TeamPinManager = {
        // Save team PIN to localStorage
        savePin: function(pin) {
            if (this.isValidPin(pin)) {
                localStorage.setItem(STORAGE_KEY, pin);
                console.log('Team PIN saved for auto-fill');
                return true;
            }
            return false;
        },
        
        // Get saved team PIN
        getPin: function() {
            return localStorage.getItem(STORAGE_KEY);
        },
        
        // Clear saved team PIN
        clearPin: function() {
            localStorage.removeItem(STORAGE_KEY);
            console.log('Team PIN cleared');
        },
        
        // Validate PIN format (6 characters)
        isValidPin: function(pin) {
            return pin && pin.length === 6 && /^[A-Za-z0-9]+$/.test(pin);
        },
        
        // Auto-fill all PIN fields on the page
        autoFillPinFields: function() {
            const savedPin = this.getPin();
            if (!savedPin) return;
            
            PIN_FIELD_SELECTORS.forEach(selector => {
                const fields = document.querySelectorAll(selector);
                fields.forEach(field => {
                    if (field && field.type !== 'hidden' && !field.value) {
                        field.value = savedPin;
                        field.classList.add('auto-filled');
                        this.addAutoFillIndicator(field);
                        
                        // Trigger change event
                        field.dispatchEvent(new Event('change', { bubbles: true }));
                        field.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                });
            });
        },
        
        // Add visual indicator for auto-filled fields
        addAutoFillIndicator: function(field) {
            // Check if indicator already exists
            const existingIndicator = field.parentNode.querySelector('.auto-fill-indicator');
            if (existingIndicator) return;
            
            const indicator = document.createElement('small');
            indicator.className = 'auto-fill-indicator text-success mt-1';
            indicator.innerHTML = '<i class="fas fa-check-circle me-1"></i>Auto-filled from saved PIN';
            indicator.style.display = 'block';
            indicator.style.fontSize = '0.8em';
            
            // Insert after the field
            if (field.parentNode) {
                field.parentNode.appendChild(indicator);
            }
        },
        
        // Remove auto-fill indicators
        clearAutoFillIndicators: function() {
            document.querySelectorAll('.auto-fill-indicator').forEach(indicator => {
                indicator.remove();
            });
            
            document.querySelectorAll('.auto-filled').forEach(field => {
                field.classList.remove('auto-filled');
            });
        },
        
        // Setup PIN field listeners
        setupPinFieldListeners: function() {
            PIN_FIELD_SELECTORS.forEach(selector => {
                const fields = document.querySelectorAll(selector);
                fields.forEach(field => {
                    if (field && field.type !== 'hidden') {
                        // Save PIN when user types in a PIN field
                        field.addEventListener('input', (e) => {
                            const pin = e.target.value.trim();
                            if (this.isValidPin(pin)) {
                                this.savePin(pin);
                                // Auto-fill other PIN fields on the page
                                setTimeout(() => this.autoFillPinFields(), 100);
                            }
                        });
                        
                        // Also listen for paste events
                        field.addEventListener('paste', (e) => {
                            setTimeout(() => {
                                const pin = e.target.value.trim();
                                if (this.isValidPin(pin)) {
                                    this.savePin(pin);
                                    setTimeout(() => this.autoFillPinFields(), 100);
                                }
                            }, 10);
                        });
                    }
                });
            });
        }
    };
    
    // Initialize when DOM is ready
    function initializeAutoFill() {
        // Auto-fill existing fields
        TeamPinManager.autoFillPinFields();
        
        // Setup listeners for new PIN inputs
        TeamPinManager.setupPinFieldListeners();
        
        // Re-run auto-fill when new content is loaded (for dynamic content)
        const observer = new MutationObserver(function(mutations) {
            let shouldAutoFill = false;
            mutations.forEach(function(mutation) {
                if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
                    mutation.addedNodes.forEach(function(node) {
                        if (node.nodeType === 1) { // Element node
                            // Check if new PIN fields were added
                            PIN_FIELD_SELECTORS.forEach(selector => {
                                if (node.matches && node.matches(selector) || 
                                    node.querySelector && node.querySelector(selector)) {
                                    shouldAutoFill = true;
                                }
                            });
                        }
                    });
                }
            });
            
            if (shouldAutoFill) {
                setTimeout(() => {
                    TeamPinManager.autoFillPinFields();
                    TeamPinManager.setupPinFieldListeners();
                }, 100);
            }
        });
        
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    }
    
    // Add clear PIN functionality to window for manual clearing
    window.clearSavedTeamPin = function() {
        TeamPinManager.clearPin();
        TeamPinManager.clearAutoFillIndicators();
        // Clear all PIN fields
        PIN_FIELD_SELECTORS.forEach(selector => {
            document.querySelectorAll(selector).forEach(field => {
                if (field && field.classList.contains('auto-filled')) {
                    field.value = '';
                    field.classList.remove('auto-filled');
                }
            });
        });
        alert('Saved team PIN cleared. You will need to enter your PIN again.');
    };
    
    // Add get saved PIN functionality for debugging
    window.getSavedTeamPin = function() {
        return TeamPinManager.getPin();
    };
    
    // Periodically check for team session changes (for Mêlée team reassignments)
    function checkTeamSessionChanges() {
        fetch('/auth/team/check/')
            .then(response => response.json())
            .then(data => {
                if (data.success && data.data.is_logged_in && data.data.team_pin) {
                    const currentSavedPin = TeamPinManager.getPin();
                    const serverPin = data.data.team_pin;
                    
                    // If the server has a different PIN than what we have saved, update it
                    if (currentSavedPin !== serverPin) {
                        console.log('Team PIN changed on server - updating autofill');
                        TeamPinManager.savePin(serverPin);
                        TeamPinManager.clearAutoFillIndicators();
                        TeamPinManager.autoFillPinFields();
                        
                        // Show a notification to the user
                        const notification = document.createElement('div');
                        notification.className = 'alert alert-info position-fixed top-0 start-50 translate-middle-x mt-3';
                        notification.style.zIndex = '9999';
                        notification.innerHTML = `
                            <i class="fas fa-info-circle me-2"></i>
                            <strong>Team Updated!</strong> You've been assigned to ${data.data.team_name}. Your PIN has been updated automatically.
                        `;
                        document.body.appendChild(notification);
                        
                        // Remove notification after 5 seconds
                        setTimeout(() => {
                            notification.remove();
                        }, 5000);
                    }
                }
            })
            .catch(error => {
                // Silently fail - don't disrupt user experience
                console.debug('Team session check failed:', error);
            });
    }
    
    // Check for team changes every 10 seconds (only if player is logged in)
    setInterval(checkTeamSessionChanges, 10000);
    
    // Initialize when DOM is loaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeAutoFill);
    } else {
        initializeAutoFill();
    }
    
    // Also initialize on page show (for back/forward navigation)
    window.addEventListener('pageshow', function() {
        setTimeout(initializeAutoFill, 100);
    });
    
    // Check immediately on page load
    setTimeout(checkTeamSessionChanges, 1000);
    
})();

