/* Scope the shooting/pointing accuracy charts by how observations were made.
 * Presentation-only: every panel comes from the server's consent-gated sums.
 */
(function () {
  "use strict";
  function initAccuracySwitches() {
    document.querySelectorAll("[data-accuracy-switch]").forEach(function (root) {
      var buttons = root.querySelectorAll("[data-accuracy-button]");
      var panels = root.querySelectorAll("[data-accuracy-panel]");
      buttons.forEach(function (button) {
        button.addEventListener("click", function () {
          var scope = button.getAttribute("data-accuracy-button");
          buttons.forEach(function (b) {
            b.setAttribute("aria-pressed",
              b.getAttribute("data-accuracy-button") === scope ? "true" : "false");
          });
          panels.forEach(function (panel) {
            panel.hidden = panel.getAttribute("data-accuracy-panel") !== scope;
          });
        });
      });
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAccuracySwitches);
  } else {
    initAccuracySwitches();
  }
}());
