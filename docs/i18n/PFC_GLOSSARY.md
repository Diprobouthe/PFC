# PFC Controlled Interface Translation Glossary

This glossary is the editorial source of truth for the PFC interface. It is used when reviewing the Django translation catalogs. Translations are manually controlled; automatic translation must not be used for PFC terminology.

## Languages

| Source language | Initial interface language |
|---|---|
| English (`en`) | Greek (`el`) |

## Core terminology

| English source | Context | Approved Greek translation | Notes |
|---|---|---|---|
| Home | Main application landing screen | Αρχική | Use for the global home destination. |
| My Matches | Current player action/match list | Οι αγώνες μου | Preserve the personal-action meaning. |
| Match | A recorded pétanque competition/game | Αγώνας | Do not use a generic game translation in match workflow actions. |
| Matches | Recorded pétanque matches | Αγώνες | Use in lists and navigation. |
| Court | Pétanque playing area | Γήπεδο | Never use a legal-court translation. Use contextual translation entries. |
| Courts | Multiple pétanque playing areas | Γήπεδα | Never use a legal-courts translation. Use contextual translation entries. |
| Court Complex | Pétanque venue with courts/facilities | Εγκαταστάσεις | Use for the PFC facility/venue page. |
| Team | PFC playing roster | Ομάδα | Use consistently in registration and match context. |
| Teams | PFC playing rosters | Ομάδες | — |
| Tournament | Organized competition event | Τουρνουά | Keep the established Greek sporting term. |
| Tournaments | Organized competition events | Τουρνουά | Greek form is the same in common UI use. |
| Friendly Game | Informal non-tournament match | Φιλικός αγώνας | Use in the Friendly Games feature. |
| Create Friendly | Create an informal friendly match | Δημιουργία φιλικού αγώνα | Prefer this full action phrase. |
| Join Tournament | Register for a tournament | Εγγραφή σε τουρνουά | Do not translate as merely “enter.” |
| Register My Team | Register the current team | Εγγραφή της ομάδας μου | — |
| Register Other Team | Register another team through the permitted flow | Εγγραφή άλλης ομάδας | — |
| Scan Player QR | Scan a player’s PFC QR card | Σάρωση QR παίκτη | Keep QR untranslated. |
| Start Match | Start/activate the selected match | Έναρξη αγώνα | Use in start and activation actions. |
| Score | Live/current match score | Σκορ | Use for the score interface. |
| Submit Result | Submit the completed match result | Υποβολή αποτελέσματος | Use for result submission. |
| Validate Result | Validate the other side’s submitted result | Επιβεβαίωση αποτελέσματος | Use for the validation step. |

## Translation rules

1. Do not translate PFC, PetA, QR, player names, team names, PINs, codenames, score values, URLs, API keys, WebSocket event names, or stored status codes.
2. Where an English source term is ambiguous, use Django contextual translation (`pgettext` or the template `context` attribute). Court/Courts must always use the pétanque context.
3. Keep interface actions short and use natural Greek sports language rather than literal word-by-word translations.
4. New Greek entries must be reviewed against this glossary before merging into `locale/el/LC_MESSAGES/django.po`.
5. Database-authored names and descriptions are not part of this first interface catalog and remain untranslated in this phase.
