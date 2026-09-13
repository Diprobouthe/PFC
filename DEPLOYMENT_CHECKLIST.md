# PFC Platform - Complete Deployment Checklist

## 📦 Package Contents
**File:** `pfc_platform_COMPLETE_WITH_AUTO_BILLBOARD.zip`

This package includes ALL features and fixes from the entire session:

---

## ✨ Features Included

### 1. ⏱️ Timer System (COMPLETE)
- ✅ Match-level timers with countdown display
- ✅ Tournament-level default timers
- ✅ Scenario-level timers that auto-transfer to tournaments
- ✅ Audio alerts (5-min, 1-min, expiration)
- ✅ Browser notifications
- ✅ Color-coded progress bar
- ✅ **FIXED:** Decimal display issue (now shows "01:28" instead of "01:28.053205999999999")
- ✅ **FIXED:** Timer transfer from scenario → tournament → matches

**Files Modified:**
- `matches/models.py` (line 93: int() conversion)
- `pfc_core/simple_creator.py` (lines 165-189: timer transfer logic)
- `matches/templates/matches/match_detail.html` (timer UI)

---

### 2. 📍 Automatic Billboard Registration (NEW!)
- ✅ Auto-register players when they activate matches
- ✅ Uses court complex from assigned court
- ✅ Duplicate prevention (checks existing entries)
- ✅ Error handling for missing codenames/courts
- ✅ Privacy-safe (uses codenames only)

**Files Modified:**
- `matches/views.py` (lines 20-71: auto_register_players_to_billboard function)
- `matches/views.py` (line 290: integration call)

**Documentation:**
- `AUTO_BILLBOARD_REGISTRATION.md` (comprehensive feature docs)

---

### 3. 🏆 Tournament Scenarios (ENHANCED)
- ✅ Scenario stages inline admin (visual table interface)
- ✅ Multi-stage support with 5 tournament algorithms
- ✅ Timer configuration at scenario level
- ✅ Automatic timer transfer to tournaments and matches

**Files Modified:**
- `pfc_core/simple_creator.py` (tournament creation logic)
- `tournaments/admin.py` (scenario admin interface)

---

### 4. 🎯 Practice Features (FIXED)
- ✅ InG distance category
- ✅ Petit Carreaux percentage display
- ✅ Shot tracker cleanup
- ✅ Hit rate percentage calculations

---

### 5. 🔧 Previous Features
- ✅ PIN auto-fill for quick team selection
- ✅ Smart team selection interface
- ✅ Homepage enhancements
- ✅ Match type detection and validation
- ✅ Court assignment system

---

## 🚀 Deployment Steps

### Step 1: Backup Current System
```bash
# On production server
cd /path/to/current/pfc_platform
zip -r backup_$(date +%Y%m%d_%H%M%S).zip .
```

### Step 2: Extract New Package
```bash
# Extract to temporary directory first
unzip pfc_platform_COMPLETE_WITH_AUTO_BILLBOARD.zip -d /tmp/pfc_new
```

### Step 3: Review Changes
```bash
# Compare key files
diff /path/to/current/matches/views.py /tmp/pfc_new/matches/views.py
diff /path/to/current/matches/models.py /tmp/pfc_new/matches/models.py
diff /path/to/current/pfc_core/simple_creator.py /tmp/pfc_new/pfc_core/simple_creator.py
```

### Step 4: Deploy
```bash
# Copy new files (preserve database and media)
rsync -av --exclude='*.sqlite3' --exclude='media/' --exclude='staticfiles/' /tmp/pfc_new/ /path/to/production/pfc_platform/
```

### Step 5: Install Dependencies
```bash
cd /path/to/production/pfc_platform
source venv/bin/activate
pip install -r requirements.txt
```

### Step 6: Migrate Database
```bash
# Check for migrations
python manage.py makemigrations
python manage.py migrate
```

### Step 7: Collect Static Files
```bash
python manage.py collectstatic --noinput
```

### Step 8: Restart Server
```bash
# For Render platform (automatic on git push)
# For manual deployment:
sudo systemctl restart gunicorn
sudo systemctl restart nginx
```

### Step 9: Verify Deployment
```bash
# Check logs
tail -f /var/log/pfc_platform/error.log

# Test key features:
# 1. Login as admin (Dipro / Bouthepass)
# 2. Create a match with timer
# 3. Activate match and check Billboard
# 4. Verify timer countdown works
```

---

## 🧪 Testing Checklist

### Timer System
- [ ] Create tournament with scenario that has timer
- [ ] Verify timer appears on tournament
- [ ] Create match from tournament
- [ ] Verify timer appears on match
- [ ] Activate match and verify countdown
- [ ] Check audio alerts at 5min, 1min, 0min
- [ ] Verify display shows "MM:SS" format (no decimals)

### Billboard Auto-Registration
- [ ] Create match with assigned court
- [ ] Add 4 players (2 teams)
- [ ] Activate match (both teams validate)
- [ ] Check Billboard - all 4 players should appear
- [ ] Verify message: "Auto-registered via match activation"
- [ ] Try activating another match with same player
- [ ] Verify no duplicate entries created

### Practice Features
- [ ] Create practice session
- [ ] Test InG distance category
- [ ] Test Petit Carreaux percentage
- [ ] Verify shot tracker works
- [ ] Check hit rate calculations

### General Functionality
- [ ] Login/logout works
- [ ] Tournament creation works
- [ ] Match creation works
- [ ] Court assignment works
- [ ] Player codenames display correctly

---

## 🔍 Key Files to Monitor

### After Deployment, Check These Files:

1. **matches/views.py**
   - Line 20-71: `auto_register_players_to_billboard()` function
   - Line 290: Function call in `activate_match` view

2. **matches/models.py**
   - Line 93: `time_remaining_seconds` property with `int()` conversion

3. **pfc_core/simple_creator.py**
   - Lines 165-189: Timer transfer logic in tournament creation

4. **billboard/models.py**
   - Verify BillboardEntry model unchanged

5. **players/models.py**
   - Verify PlayerCodename model unchanged

---

## 📊 Database Checks

### After Deployment, Verify:

```sql
-- Check Billboard entries created by auto-registration
SELECT * FROM billboard_billboardentry 
WHERE message = 'Auto-registered via match activation'
ORDER BY created_at DESC
LIMIT 10;

-- Check matches with timers
SELECT id, tournament_id, time_limit_minutes, start_time, status
FROM matches_match
WHERE time_limit_minutes IS NOT NULL
ORDER BY created_at DESC
LIMIT 10;

-- Check player codenames
SELECT p.name, pc.codename
FROM players_player p
LEFT JOIN players_playercodename pc ON p.id = pc.player_id
LIMIT 10;
```

---

## 🐛 Troubleshooting

### Issue: Timer shows decimals
**Solution:** Check line 93 in `matches/models.py` has `int()` conversion:
```python
return int(remaining.total_seconds())
```

### Issue: Timer not transferring from scenario
**Solution:** Check `pfc_core/simple_creator.py` lines 165-189 for timer transfer logic

### Issue: Players not auto-registering to Billboard
**Possible Causes:**
1. Match has no assigned court → Check court assignment
2. Court has no court complex → Check court configuration
3. Player has no codename → Check PlayerCodename records
4. Function not called → Check line 290 in `matches/views.py`

**Debug Steps:**
```bash
# Check logs for auto-registration
grep "Auto-registered player" /var/log/pfc_platform/info.log
grep "Billboard registration" /var/log/pfc_platform/warning.log
```

### Issue: CSRF errors
**Solution:** Ensure `CSRF_TRUSTED_ORIGINS` in `settings.py` includes your domain:
```python
CSRF_TRUSTED_ORIGINS = [
    'https://your-domain.com',
    'https://*.render.com',
]
```

---

## 📝 Admin Credentials

**Username:** Dipro  
**Password:** Bouthepass

**Important:** Change password after first login in production!

---

## 🔐 Security Notes

### Before Production Deployment:

1. **Change Secret Key**
   ```python
   # In settings.py
   SECRET_KEY = 'your-new-secret-key-here'
   ```

2. **Set DEBUG to False**
   ```python
   # In settings.py
   DEBUG = False
   ```

3. **Configure Allowed Hosts**
   ```python
   # In settings.py
   ALLOWED_HOSTS = ['your-domain.com', 'www.your-domain.com']
   ```

4. **Set Up HTTPS**
   - Configure SSL certificate
   - Force HTTPS redirects
   - Set secure cookie flags

5. **Change Admin Password**
   ```bash
   python manage.py changepassword Dipro
   ```

---

## 📚 Documentation Files Included

1. **AUTO_BILLBOARD_REGISTRATION.md**
   - Complete feature documentation
   - User flow comparison
   - Testing scenarios
   - Privacy & security notes

2. **DEPLOYMENT_CHECKLIST.md** (this file)
   - Deployment steps
   - Testing checklist
   - Troubleshooting guide

3. **README.md** (if exists)
   - General project documentation

---

## ✅ Pre-Deployment Verification

Before deploying, verify these items:

- [ ] Backup of current system created
- [ ] All required dependencies in requirements.txt
- [ ] Database migrations ready
- [ ] Static files configured
- [ ] Environment variables set
- [ ] CSRF settings configured
- [ ] Admin credentials ready
- [ ] Rollback plan prepared

---

## 🎯 Success Criteria

Deployment is successful when:

- ✅ All pages load without errors
- ✅ Admin can login with credentials
- ✅ Timers display correctly (MM:SS format)
- ✅ Timers countdown in real-time
- ✅ Audio alerts play at correct times
- ✅ Players auto-register to Billboard on match activation
- ✅ No duplicate Billboard entries created
- ✅ Tournament creation works with scenarios
- ✅ Practice sessions work correctly
- ✅ No CSRF errors on forms

---

## 📞 Support

If issues arise during deployment:

1. Check logs: `/var/log/pfc_platform/`
2. Review Django debug output
3. Verify database migrations applied
4. Check static files collected
5. Verify environment variables set

---

## 🎉 Summary

This package includes:
- ⏱️ Complete timer system with all fixes
- 📍 Automatic Billboard registration (NEW!)
- 🏆 Enhanced tournament scenarios
- 🎯 Fixed practice features
- 🔧 All previous features and improvements

**Total Files Modified:** ~15 files across matches, tournaments, billboard, players, and pfc_core apps

**Database Changes:** None (uses existing models)

**Migration Required:** No

**Server Restart Required:** Yes

---

**Ready to deploy! 🚀**
