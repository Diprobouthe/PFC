# PFC Court Complex Live Detail Update

## Included files

- `courts/views.py`
- `courts/templates/courts/court_complex_detail.html`
- `courts/tests/__init__.py`
- `courts/tests/test_complex_detail_live_context.py`

## Scope

This update redesigns the existing Court Complex detail page. For Court Complexes with configured coordinates, it adds a read-only, venue-specific live section built from the existing Billboard records:

- current source-aware `AT_COURTS` presence;
- current active `GOING_TO_COURTS` declarations and expected arrival time;
- the existing Friendly eligibility calculation for the `Available for Friendly` indicator; and
- the existing non-stale `CommunityPresenceReport`.

The page preserves the existing description, gallery, court list, maps/access, facility information, ratings, reviews, and rating submission flow. Non-geolocated Court Complexes do not receive the live physical-presence section.

## Deployment

No migration or environment-variable change is required. Deploy the included files through the normal Render deployment process.

## Verification

`python3 manage.py test courts.tests.test_complex_detail_live_context --verbosity 2` passed.

`python3 manage.py check` passed with 0 issues.

`python3 manage.py makemigrations --check --dry-run courts` reported no changes.
