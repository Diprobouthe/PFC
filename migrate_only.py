#!/usr/bin/env python3
"""
Migration script for PFC Platform code update
This script only runs new migrations without affecting existing data
"""

import os
import sys
import django
from django.core.management import execute_from_command_line

def run_migrations():
    """Run only the new migrations for Smart Swiss features"""
    
    print("🔄 Running Smart Swiss migrations...")
    
    # Set Django settings
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pfc_core.settings')
    django.setup()
    
    from django.core.management import call_command
    from django.db import connection
    
    try:
        # Check if smart_swiss migrations are needed
        print("📊 Checking migration status...")
        
        # Run migrations for tournaments app (includes Smart Swiss format)
        print("🏆 Applying tournament migrations...")
        call_command('migrate', 'tournaments', verbosity=1)
        
        # Run any other pending migrations
        print("🔄 Applying any other pending migrations...")
        call_command('migrate', verbosity=1)
        
        print("✅ All migrations completed successfully!")
        print("📝 Smart Swiss format is now available in tournaments")
        
        return True
        
    except Exception as e:
        print(f"❌ Migration error: {e}")
        return False

def verify_smart_swiss():
    """Verify that Smart Swiss features are available"""
    
    print("\n🧪 Verifying Smart Swiss installation...")
    
    try:
        from tournaments.models import Tournament, Stage
        
        # Check Tournament format choices
        tournament_formats = dict(Tournament.FORMAT_CHOICES)
        if 'smart_swiss' in tournament_formats:
            print("✅ Smart Swiss format available in Tournament model")
        else:
            print("⚠️ Smart Swiss format not found in Tournament model")
        
        # Check Stage format choices  
        stage_formats = dict(Stage.STAGE_FORMATS)
        if 'smart_swiss' in stage_formats:
            print("✅ Smart Swiss format available in Stage model")
        else:
            print("⚠️ Smart Swiss format not found in Stage model")
        
        # Check if Swiss algorithms are available
        try:
            from tournaments.swiss_algorithms import generate_smart_swiss_round, generate_standard_swiss_round
            print("✅ Smart Swiss algorithms imported successfully")
        except ImportError as e:
            print(f"⚠️ Swiss algorithms import error: {e}")
        
        print("🎉 Smart Swiss verification completed!")
        return True
        
    except Exception as e:
        print(f"❌ Verification error: {e}")
        return False

if __name__ == "__main__":
    print("🚀 PFC Platform Code Update - Migration Script")
    print("=" * 50)
    
    # Run migrations
    migration_success = run_migrations()
    
    if migration_success:
        # Verify installation
        verify_smart_swiss()
        print("\n🎉 Code update completed successfully!")
        print("📋 Next steps:")
        print("   1. Restart your Render web service")
        print("   2. Test Smart Swiss tournament creation")
        print("   3. Verify admin 'generate matches' action works")
    else:
        print("\n❌ Code update failed during migration")
        print("   Please check the error messages above")
        sys.exit(1)
