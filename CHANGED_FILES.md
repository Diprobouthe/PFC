# Changed Files — Simple Tournament Player Registration Removal

| Archive path | Status | Purpose |
|---|---|---|
| `pfc_core/simple_creator.py` | Modified | Adds the POST-only, CSRF-protected pre-start `MeleePlayer` registration removal action and Management access/lifecycle checks. |
| `pfc_core/urls.py` | Modified | Registers the live removal endpoint under the existing `/simple/manage/` route family. |
| `templates/simple_tournament_manage.html` | Modified | Adds the compact right-aligned `×` control only for authorized pre-start individual Mêlée registrations. |
| `pfc_core/tests/test_simple_tournament_registration_removal.py` | New | Covers authorization, staff override, CSRF rejection, lifecycle rejection, re-registration, isolation, and preserved start availability. |
| `README.md` | New | Scope, deployment, verification, and lifecycle guidance. |
| `CHANGED_FILES.md` | New | This exact manifest. |

No migration, model, settings, legacy Simple Tournament source, player account, Team, scoring, lifecycle, match, or Tournament progression file was changed.
