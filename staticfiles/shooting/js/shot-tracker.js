/**
 * Shot Accuracy Tracker Widget
 * 
 * Ultra-simple in-play shot tracking with Hit/Miss buttons.
 * Optimized for mobile with big tap targets and minimal cognitive load.
 */

class ShotTracker {
    constructor(container, options = {}) {
        this.container = container;
        this.options = {
            mode: 'practice', // 'practice' or 'ingame'
            matchId: null,
            inning: null,
            apiBaseUrl: '/api/shoot/',
            csrfToken: this.getCSRFToken(),
            ...options
        };
        
        this.session = null;
        this.isLoading = false;
        this.lastShotTime = 0;
        this.minInterval = 300; // 300ms minimum between shots
        
        this.init();
    }
    
    init() {
        this.render();
        this.bindEvents();
        this.checkActiveSession();
    }
    
    render() {
        this.container.innerHTML = `
            <div class="shot-tracker-widget" id="shotTracker">
                <div class="shot-tracker-header">
                    <h3 class="shot-tracker-title">
                        <span class="icon">🎯</span>
                        Shot Tracker (Beta)
                    </h3>
                    <div class="shot-tracker-mode">${this.options.mode}</div>
                </div>
                
                <div class="shot-tracker-content">
                    ${this.renderNoSession()}
                </div>
            </div>
        `;
    }
    
    renderNoSession() {
        return `
            <div class="shot-tracker-start">
                <p style="text-align: center; margin-bottom: 20px; opacity: 0.9;">
                    Start tracking your shooting accuracy
                </p>
                <button class="shot-btn shot-btn-hit" onclick="shotTracker.startSession()" style="width: 100%;">
                    <span class="icon">▶️</span>
                    Start Session
                </button>
            </div>
        `;
    }
    
    renderActiveSession() {
        if (!this.session) return this.renderNoSession();
        
        return `
            <div class="shot-tracker-buttons">
                <button class="shot-btn shot-btn-hit" onclick="shotTracker.recordShot(true)" ${this.isLoading ? 'disabled' : ''}>
                    <span class="icon">✅</span>
                    Hit
                </button>
                <button class="shot-btn shot-btn-miss" onclick="shotTracker.recordShot(false)" ${this.isLoading ? 'disabled' : ''}>
                    <span class="icon">❌</span>
                    Miss
                </button>
            </div>
            
            <div class="shot-stats">
                <div class="stat-item">
                    <span class="stat-value">${this.session.current_streak || 0}</span>
                    <span class="stat-label">Streak</span>
                </div>
                <div class="stat-item">
                    <span class="stat-value">${this.session.best_streak || 0}</span>
                    <span class="stat-label">Best</span>
                </div>
                <div class="stat-item">
                    <span class="stat-value">${this.session.total_shots || 0}</span>
                    <span class="stat-label">Shots</span>
                </div>
                <div class="stat-item">
                    <span class="stat-value">${Math.round((this.session.hit_rate || 0) * 100)}%</span>
                    <span class="stat-label">Hit %</span>
                </div>
            </div>
            
            <div class="shot-controls">
                <button class="control-btn" onclick="shotTracker.undoLastShot()" ${this.isLoading || this.session.total_shots === 0 ? 'disabled' : ''}>
                    Undo
                </button>
                <button class="control-btn danger" onclick="shotTracker.endSession()" ${this.isLoading ? 'disabled' : ''}>
                    End
                </button>
            </div>
        `;
    }
    
    renderError(message) {
        return `
            <div class="shot-tracker-error">
                <div class="error-message">${message}</div>
                <button class="retry-btn" onclick="shotTracker.checkActiveSession()">
                    Retry
                </button>
            </div>
        `;
    }
    
    updateContent(html) {
        const content = this.container.querySelector('.shot-tracker-content');
        if (content) {
            content.innerHTML = html;
        }
    }
    
    setLoading(loading) {
        this.isLoading = loading;
        const widget = this.container.querySelector('.shot-tracker-widget');
        if (widget) {
            widget.classList.toggle('shot-tracker-loading', loading);
        }
    }
    
    bindEvents() {
        // Add haptic feedback for mobile
        if ('vibrate' in navigator) {
            this.container.addEventListener('click', (e) => {
                if (e.target.classList.contains('shot-btn')) {
                    navigator.vibrate(50); // Short vibration
                }
            });
        }
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (!this.session || this.isLoading) return;
            
            if (e.key === 'h' || e.key === 'H') {
                e.preventDefault();
                this.recordShot(true);
            } else if (e.key === 'm' || e.key === 'M') {
                e.preventDefault();
                this.recordShot(false);
            } else if (e.key === 'u' || e.key === 'U') {
                e.preventDefault();
                this.undoLastShot();
            }
        });
    }
    
    async checkActiveSession() {
        try {
            const response = await this.apiCall('GET', 'active-session/');
            
            if (response.ok) {
                this.session = await response.json();
                this.updateContent(this.renderActiveSession());
            } else if (response.status === 404) {
                // No active session
                this.session = null;
                this.updateContent(this.renderNoSession());
            } else {
                throw new Error('Failed to check active session');
            }
        } catch (error) {
            console.error('Error checking active session:', error);
            this.updateContent(this.renderError('Failed to load session'));
        }
    }
    
    async startSession() {
        if (this.isLoading) return;
        
        this.setLoading(true);
        
        try {
            const sessionData = {
                mode: this.options.mode
            };
            
            if (this.options.mode === 'ingame' && this.options.matchId) {
                sessionData.match_id = this.options.matchId;
            }
            
            if (this.options.inning) {
                sessionData.inning = this.options.inning;
            }
            
            const response = await this.apiCall('POST', 'sessions/', sessionData);
            
            if (response.ok) {
                const result = await response.json();
                // Fetch the full session data
                await this.loadSession(result.session_id);
            } else {
                const error = await response.json();
                throw new Error(error.error || 'Failed to start session');
            }
        } catch (error) {
            console.error('Error starting session:', error);
            this.showError(error.message);
        } finally {
            this.setLoading(false);
        }
    }
    
    async loadSession(sessionId) {
        try {
            const response = await this.apiCall('GET', `sessions/${sessionId}/`);
            
            if (response.ok) {
                this.session = await response.json();
                this.updateContent(this.renderActiveSession());
            } else {
                throw new Error('Failed to load session');
            }
        } catch (error) {
            console.error('Error loading session:', error);
            this.showError('Failed to load session');
        }
    }
    
    async recordShot(isHit) {
        if (this.isLoading || !this.session) return;
        
        // Rate limiting check
        const now = Date.now();
        if (now - this.lastShotTime < this.minInterval) {
            return; // Too soon, ignore
        }
        this.lastShotTime = now;
        
        this.setLoading(true);
        
        try {
            const response = await this.apiCall('POST', `sessions/${this.session.id}/event/`, {
                is_hit: isHit
            });
            
            if (response.ok) {
                const result = await response.json();
                
                // Update session data
                this.session.total_shots = result.total_shots;
                this.session.total_hits = result.total_hits;
                this.session.current_streak = result.current_streak;
                this.session.best_streak = result.best_streak;
                this.session.hit_rate = result.hit_rate;
                
                // Show achievements if any
                if (result.unlocked && result.unlocked.length > 0) {
                    result.unlocked.forEach(achievement => {
                        this.showAchievement(achievement);
                    });
                }
                
                this.updateContent(this.renderActiveSession());
            } else {
                const error = await response.json();
                throw new Error(error.error || 'Failed to record shot');
            }
        } catch (error) {
            console.error('Error recording shot:', error);
            this.showError(error.message);
        } finally {
            this.setLoading(false);
        }
    }
    
    async undoLastShot() {
        if (this.isLoading || !this.session || this.session.total_shots === 0) return;
        
        this.setLoading(true);
        
        try {
            const response = await this.apiCall('POST', `sessions/${this.session.id}/undo/`);
            
            if (response.ok) {
                const result = await response.json();
                
                // Update session data
                this.session.total_shots = result.total_shots;
                this.session.total_hits = result.total_hits;
                this.session.current_streak = result.current_streak;
                this.session.best_streak = result.best_streak;
                this.session.hit_rate = result.hit_rate;
                
                this.updateContent(this.renderActiveSession());
            } else {
                const error = await response.json();
                throw new Error(error.error || 'Failed to undo shot');
            }
        } catch (error) {
            console.error('Error undoing shot:', error);
            this.showError(error.message);
        } finally {
            this.setLoading(false);
        }
    }
    
    async endSession() {
        if (this.isLoading || !this.session) return;
        
        if (!confirm('Are you sure you want to end this session?')) {
            return;
        }
        
        this.setLoading(true);
        
        try {
            const response = await this.apiCall('POST', `sessions/${this.session.id}/end/`);
            
            if (response.ok) {
                this.session = null;
                this.updateContent(this.renderNoSession());
            } else {
                const error = await response.json();
                throw new Error(error.error || 'Failed to end session');
            }
        } catch (error) {
            console.error('Error ending session:', error);
            this.showError(error.message);
        } finally {
            this.setLoading(false);
        }
    }
    
    showAchievement(achievement) {
        const notification = document.createElement('div');
        notification.className = 'achievement-notification';
        notification.innerHTML = `
            <div class="achievement-text">
                <span class="achievement-icon">${achievement.icon || '🏆'}</span>
                <div>
                    <strong>Achievement Unlocked!</strong><br>
                    ${achievement.name}
                </div>
            </div>
        `;
        
        document.body.appendChild(notification);
        
        // Trigger animation
        setTimeout(() => {
            notification.classList.add('show');
        }, 100);
        
        // Remove after 4 seconds
        setTimeout(() => {
            notification.classList.remove('show');
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 300);
        }, 4000);
    }
    
    showError(message) {
        // Simple error display - could be enhanced with toast notifications
        alert(`Error: ${message}`);
    }
    
    async apiCall(method, endpoint, data = null) {
        const url = this.options.apiBaseUrl + endpoint;
        const config = {
            method,
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.options.csrfToken
            }
        };
        
        if (data) {
            config.body = JSON.stringify(data);
        }
        
        return fetch(url, config);
    }
    
    getCSRFToken() {
        // Get CSRF token from cookie or meta tag
        const cookieValue = document.cookie
            .split('; ')
            .find(row => row.startsWith('csrftoken='))
            ?.split('=')[1];
            
        if (cookieValue) return cookieValue;
        
        // Try meta tag
        const metaTag = document.querySelector('meta[name="csrf-token"]');
        return metaTag ? metaTag.getAttribute('content') : '';
    }
}

// Global instance for easy access from HTML
let shotTracker = null;

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    const container = document.getElementById('shot-tracker-container');
    if (container) {
        // Get options from data attributes
        const options = {
            mode: container.dataset.mode || 'practice',
            matchId: container.dataset.matchId || null,
            inning: container.dataset.inning ? parseInt(container.dataset.inning) : null
        };
        
        shotTracker = new ShotTracker(container, options);
    }
});

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ShotTracker;
}
