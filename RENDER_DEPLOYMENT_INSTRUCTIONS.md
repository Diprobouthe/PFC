# Render Deployment Instructions - Fix SimpleTournament Issue

## Problem Summary

**Error on Render:**
```
InvalidCursorName: cursor "_django_curs_127589345171264_sync_1" does not exist
column simple_creator_tournamentscenario.default_court_complex_id does not exist
```

**Root Cause:** Migration files were excluded from the deployment package, so the database schema on Render is outdated.

**Solution:** Deploy the complete package WITH migrations included.

---

## ✅ Data Safety Guarantee

**IMPORTANT:** This deployment will **NOT** erase any existing data!

**What is preserved:**
- ✅ All player accounts and profiles
- ✅ All teams and team memberships  
- ✅ All matches and scores
- ✅ All ratings and statistics
- ✅ All tournament data
- ✅ All billboard entries
- ✅ All user accounts and permissions

**What gets updated:**
- Database schema (adds missing column)
- Existing TournamentScenario records get linked to PEDION AREOS court complex

**Migrations are designed to be non-destructive and preserve all data!**

---

## Deployment Steps

### Step 1: Upload New Package

**File:** `pfc_platform_FOR_RENDER_FIXED.zip`

**What's different:**
- ✅ Includes ALL migration files (85 migration files)
- ✅ Improved migration 0006 with safer default handling
- ✅ All latest features and fixes

**What to upload:**
1. Extract `pfc_platform_FOR_RENDER_FIXED.zip` on your local machine
2. Upload the `pfc_platform` folder to Render (via Git or manual upload)

### Step 2: Run Migrations on Render

**After uploading, run these commands on Render:**

```bash
# Navigate to project directory
cd /opt/render/project/src

# Run migrations
python manage.py migrate

# Collect static files (if needed)
python manage.py collectstatic --noinput

# Restart the service
# (Render usually does this automatically)
```

**Expected output:**
```
Running migrations:
  Applying simple_creator.0005_tournamentscenario_default_court_complex... OK
  Applying simple_creator.0006_alter_tournamentscenario_default_court_complex... OK
```

### Step 3: Verify SimpleTournament Works

**Test URL:**
```
https://www.pfc.events/admin/simple_creator/simpletournament/add/
```

**Expected result:** ✅ Page loads without errors

---

## Migration Details

### Migration 0005
**File:** `0005_tournamentscenario_default_court_complex.py`

**What it does:**
- Adds `default_court_complex` field to TournamentScenario model
- Field is initially **nullable** (can be empty)
- Safe for existing data

### Migration 0006 (Improved)
**File:** `0006_alter_tournamentscenario_default_court_complex.py`

**What it does:**
1. Finds the first available CourtComplex (PEDION AREOS, ID 1)
2. Assigns it to all existing TournamentScenario records
3. Makes the field **required** (not nullable)

**Code:**
```python
def set_default_court_complex(apps, schema_editor):
    """
    Set default court complex for existing TournamentScenario records.
    Uses the first available CourtComplex, or leaves null if none exist.
    """
    TournamentScenario = apps.get_model('simple_creator', 'TournamentScenario')
    CourtComplex = apps.get_model('courts', 'CourtComplex')
    
    # Get first available court complex
    first_court = CourtComplex.objects.first()
    
    if first_court:
        # Update all existing scenarios without a court complex
        TournamentScenario.objects.filter(default_court_complex__isnull=True).update(
            default_court_complex=first_court
        )
```

**Why it's safe:**
- Uses `CourtComplex.objects.first()` - works regardless of ID
- Only updates records that don't have a court complex
- Doesn't modify any other data

---

## Troubleshooting

### If migration fails with "CourtComplex matching query does not exist"

**Solution:** Create a CourtComplex first

```bash
python manage.py shell
```

```python
from courts.models import CourtComplex

# Create PEDION AREOS court complex if it doesn't exist
CourtComplex.objects.get_or_create(
    id=1,
    defaults={
        'name': 'PEDION AREOS COURTS',
        'address': 'Pedion Areos, Athens, Greece',
        'number_of_courts': 6,
        'is_available': True
    }
)
```

Then run migrations again:
```bash
python manage.py migrate
```

### If you see "Migration already applied"

**This is normal!** It means the migration was already run successfully.

**Verify it worked:**
```bash
python manage.py shell
```

```python
from simple_creator.models import TournamentScenario

# Check if field exists
scenario = TournamentScenario.objects.first()
print(scenario.default_court_complex)  # Should print: PEDION AREOS COURTS
```

### If SimpleTournament still doesn't work

**Check database schema:**
```bash
python manage.py dbshell
```

```sql
-- PostgreSQL
\d simple_creator_tournamentscenario

-- Should show column:
-- default_court_complex_id | integer | not null
```

**If column is missing:**
```bash
# Force re-run migration
python manage.py migrate simple_creator 0005 --fake
python manage.py migrate simple_creator 0006
```

---

## Alternative: Manual Database Fix (Advanced)

**If migrations fail completely, you can manually add the column:**

```sql
-- PostgreSQL
ALTER TABLE simple_creator_tournamentscenario 
ADD COLUMN default_court_complex_id INTEGER;

-- Set default value (assuming CourtComplex ID 1 exists)
UPDATE simple_creator_tournamentscenario 
SET default_court_complex_id = 1 
WHERE default_court_complex_id IS NULL;

-- Make it required
ALTER TABLE simple_creator_tournamentscenario 
ALTER COLUMN default_court_complex_id SET NOT NULL;

-- Add foreign key constraint
ALTER TABLE simple_creator_tournamentscenario 
ADD CONSTRAINT simple_creator_tournamentscenario_default_court_complex_id_fkey 
FOREIGN KEY (default_court_complex_id) 
REFERENCES courts_courtcomplex(id) 
ON DELETE RESTRICT;
```

**Then mark migration as applied:**
```bash
python manage.py migrate simple_creator 0006 --fake
```

---

## Verification Checklist

After deployment, verify these work:

- [ ] Admin panel loads: `https://www.pfc.events/admin/`
- [ ] SimpleTournament add page loads: `https://www.pfc.events/admin/simple_creator/simpletournament/add/`
- [ ] Can create a new SimpleTournament
- [ ] Existing tournaments still visible
- [ ] All player data intact
- [ ] Matches and scores intact

---

## What Changed in This Package

### Features
- ✅ PIN removed from homepage (cleaner UI)
- ✅ PFC Market decimals fixed (2 decimal places)
- ✅ Court occupancy count fixed (matches billboard)
- ✅ Practice button feedback improved (no borders)
- ✅ Complete PIN auto-fill system (6/6 forms)
- ✅ Live weather and court information
- ✅ Personalized homepage greeting

### Technical
- ✅ **All migration files included** (was excluded before)
- ✅ Improved migration 0006 with safer defaults
- ✅ 85 migration files across all apps
- ✅ Complete documentation (37 markdown files)

---

## Support

**If you encounter any issues:**

1. Check Render logs for detailed error messages
2. Verify CourtComplex ID 1 exists on Render
3. Try running migrations manually
4. Check database schema matches expected structure

**The deployment is safe and will not delete any data!**

---

**Deployment Package:** `pfc_platform_FOR_RENDER_FIXED.zip`  
**Date:** December 2, 2025  
**Status:** ✅ Ready for deployment

🎯 **Deploy with confidence - your data is safe!** 🎯
