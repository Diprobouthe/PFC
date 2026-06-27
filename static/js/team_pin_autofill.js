// Team PIN Auto-Fill System
// Provides auto-fill for team PINs and detects server-side team reassignments.
//
// Polling policy (scoped to Mêlée / Super Mêlée dynamic assignment):
//   • in_melee_assignment=true  → fast 10-second loop (player is in an active
//                                  Mêlée assignment window and their team may
//                                  change without them initiating the request).
//   • in_melee_assignment=false → NO recurring loop.  A single check fires on
//                                  page load and again on tab focus, which is
//                                  enough for all other contexts.
//   • Tab hidden                → polling paused regardless of mode.
//   • Anonymous visitors        → this script is only loaded for logged-in
//                                  players (base.html wraps the <script> tag
//                                  inside {% if session_codename %}).

(function () {
    'use strict';

    // ── Configuration ────────────────────────────────────────────────────────
    const STORAGE_KEY         = 'pfc_team_pin';
    const MELEE_INTERVAL_MS   = 10000;   // 10 s — only during Mêlée assignment
    const CHECK_ENDPOINT      = '/auth/team/check/';

    const PIN_FIELD_SELECTORS = [
        'input[placeholder*="*"]',
        'input[name*="pin"]',
        'input[id*="pin"]',
        '.team-pin-field'
    ];

    // ── Team PIN Manager ─────────────────────────────────────────────────────
    const TeamPinManager = {
        savePin: function (pin) {
            if (this.isValidPin(pin)) {
                localStorage.setItem(STORAGE_KEY, pin);
                return true;
            }
            return false;
        },

        getPin: function () {
            return localStorage.getItem(STORAGE_KEY);
        },

        clearPin: function () {
            localStorage.removeItem(STORAGE_KEY);
        },

        isValidPin: function (pin) {
            return pin && pin.length === 6 && /^[A-Za-z0-9]+$/.test(pin);
        },

        autoFillPinFields: function () {
            const savedPin = this.getPin();
            if (!savedPin) return;

            PIN_FIELD_SELECTORS.forEach(selector => {
                document.querySelectorAll(selector).forEach(field => {
                    if (field && field.type !== 'hidden' && !field.value) {
                        field.value = savedPin;
                        field.classList.add('auto-filled');
                        this._addIndicator(field);
                        field.dispatchEvent(new Event('change', { bubbles: true }));
                        field.dispatchEvent(new Event('input',  { bubbles: true }));
                    }
                });
            });
        },

        _addIndicator: function (field) {
            if (field.parentNode.querySelector('.auto-fill-indicator')) return;
            const el = document.createElement('small');
            el.className = 'auto-fill-indicator text-success mt-1';
            el.style.cssText = 'display:block;font-size:0.8em';
            el.innerHTML = '<i class="fas fa-check-circle me-1"></i>Auto-filled from saved PIN';
            field.parentNode.appendChild(el);
        },

        clearAutoFillIndicators: function () {
            document.querySelectorAll('.auto-fill-indicator').forEach(el => el.remove());
            document.querySelectorAll('.auto-filled').forEach(el => el.classList.remove('auto-filled'));
        },

        setupPinFieldListeners: function () {
            PIN_FIELD_SELECTORS.forEach(selector => {
                document.querySelectorAll(selector).forEach(field => {
                    if (!field || field.type === 'hidden') return;
                    field.addEventListener('input', e => {
                        const pin = e.target.value.trim();
                        if (this.isValidPin(pin)) {
                            this.savePin(pin);
                            setTimeout(() => this.autoFillPinFields(), 100);
                        }
                    });
                    field.addEventListener('paste', e => {
                        setTimeout(() => {
                            const pin = e.target.value.trim();
                            if (this.isValidPin(pin)) {
                                this.savePin(pin);
                                setTimeout(() => this.autoFillPinFields(), 100);
                            }
                        }, 10);
                    });
                });
            });
        }
    };

    // ── Session check & polling controller ──────────────────────────────────
    let _meleeIntervalId = null;   // handle for the fast Mêlée polling loop
    let _checkInFlight   = false;  // prevent overlapping requests

    function checkTeamSessionChanges() {
        // Skip if tab is hidden (saves requests when user switches tabs)
        if (document.visibilityState === 'hidden') return;
        // Skip if a request is already in-flight
        if (_checkInFlight) return;

        _checkInFlight = true;
        fetch(CHECK_ENDPOINT)
            .then(r => r.json())
            .then(data => {
                if (!data.success) return;

                const d = data.data;

                // ── 1. Update PIN autofill if team changed ────────────────
                if (d.is_logged_in && d.team_pin) {
                    const currentPin = TeamPinManager.getPin();
                    if (currentPin !== d.team_pin) {
                        console.log('[PFC] Team PIN changed on server — updating autofill');
                        TeamPinManager.savePin(d.team_pin);
                        TeamPinManager.clearAutoFillIndicators();
                        TeamPinManager.autoFillPinFields();

                        // Show in-page notification
                        const note = document.createElement('div');
                        note.className = 'alert alert-info position-fixed top-0 start-50 translate-middle-x mt-3';
                        note.style.zIndex = '9999';
                        note.innerHTML =
                            '<i class="fas fa-info-circle me-2"></i>' +
                            '<strong>Team Updated!</strong> You\'ve been assigned to ' +
                            (d.team_name || 'a new team') + '. Your PIN has been updated automatically.';
                        document.body.appendChild(note);
                        setTimeout(() => note.remove(), 5000);
                    }
                }

                // ── 2. Adjust polling mode based on in_melee_assignment ───
                const inMelee = !!d.in_melee_assignment;

                if (inMelee && !_meleeIntervalId) {
                    // Player just entered Mêlée assignment → start fast loop
                    console.log('[PFC] Mêlée assignment active — starting fast team-check polling');
                    _meleeIntervalId = setInterval(checkTeamSessionChanges, MELEE_INTERVAL_MS);

                } else if (!inMelee && _meleeIntervalId) {
                    // Player left Mêlée assignment → stop fast loop
                    console.log('[PFC] Mêlée assignment ended — stopping fast team-check polling');
                    clearInterval(_meleeIntervalId);
                    _meleeIntervalId = null;
                }
            })
            .catch(err => {
                console.debug('[PFC] Team session check failed:', err);
            })
            .finally(() => {
                _checkInFlight = false;
            });
    }

    // ── Auto-fill initialisation ─────────────────────────────────────────────
    function initializeAutoFill() {
        TeamPinManager.autoFillPinFields();
        TeamPinManager.setupPinFieldListeners();

        // Re-run auto-fill when new PIN fields are injected into the DOM
        const observer = new MutationObserver(mutations => {
            let shouldFill = false;
            mutations.forEach(m => {
                if (m.type === 'childList') {
                    m.addedNodes.forEach(node => {
                        if (node.nodeType !== 1) return;
                        PIN_FIELD_SELECTORS.forEach(sel => {
                            if ((node.matches && node.matches(sel)) ||
                                (node.querySelector && node.querySelector(sel))) {
                                shouldFill = true;
                            }
                        });
                    });
                }
            });
            if (shouldFill) {
                setTimeout(() => {
                    TeamPinManager.autoFillPinFields();
                    TeamPinManager.setupPinFieldListeners();
                }, 100);
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    // ── Public helpers ───────────────────────────────────────────────────────
    window.clearSavedTeamPin = function () {
        TeamPinManager.clearPin();
        TeamPinManager.clearAutoFillIndicators();
        PIN_FIELD_SELECTORS.forEach(sel => {
            document.querySelectorAll(sel).forEach(field => {
                if (field && field.classList.contains('auto-filled')) {
                    field.value = '';
                    field.classList.remove('auto-filled');
                }
            });
        });
        alert('Saved team PIN cleared. You will need to enter your PIN again.');
    };

    window.getSavedTeamPin = function () {
        return TeamPinManager.getPin();
    };

    // ── Startup ──────────────────────────────────────────────────────────────
    // Single check on page load (determines whether Mêlée loop should start)
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            initializeAutoFill();
            setTimeout(checkTeamSessionChanges, 500);
        });
    } else {
        initializeAutoFill();
        setTimeout(checkTeamSessionChanges, 500);
    }

    // Single check on tab focus (catches changes that happened while tab was hidden)
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible') {
            checkTeamSessionChanges();
        }
    });

    // Single check on back/forward navigation
    window.addEventListener('pageshow', function () {
        setTimeout(checkTeamSessionChanges, 200);
    });

})();
