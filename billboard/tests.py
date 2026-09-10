from pathlib import Path

from django.test import SimpleTestCase


class ManualHereLocationRetryTemplateTests(SimpleTestCase):
    """Protect the focused client-side pre-verification retry contract."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        template_path = Path(__file__).parent / "templates" / "billboard" / "billboard_list.html"
        cls.template = template_path.read_text(encoding="utf-8")

    def test_position_unavailable_and_timeout_retry_once_with_longer_timeout(self):
        self.assertIn("const MANUAL_HERE_INITIAL_TIMEOUT_MS=15000;", self.template)
        self.assertIn("const MANUAL_HERE_RETRY_TIMEOUT_MS=20000;", self.template)
        self.assertIn("if(firstCode!==2&&firstCode!==3) throw firstError;", self.template)
        self.assertIn(
            "requestManualHereLocation(MANUAL_HERE_RETRY_TIMEOUT_MS)",
            self.template,
        )
        self.assertIn("enableHighAccuracy:true", self.template)
        self.assertIn("maximumAge:0", self.template)

    def test_browser_codes_and_request_failures_have_distinct_paths(self):
        self.assertIn("else if(e&&e.code===1)", self.template)
        self.assertIn("else if(e&&e.code===2)", self.template)
        self.assertIn("else if(e&&e.code===3)", self.template)
        self.assertIn("pfcRequestFailure:true", self.template)
        self.assertIn("PFC obtained your location, but the check-in request", self.template)
        self.assertIn("browser error.code", self.template)
        self.assertIn("browser error.message", self.template)

    def test_successful_location_keeps_accuracy_aware_payload_fields(self):
        self.assertIn("payload.accuracy=position.coords.accuracy;", self.template)
        self.assertIn("payload.position_timestamp=position.timestamp;", self.template)
        self.assertIn("await submitManualHere(position,null);", self.template)
