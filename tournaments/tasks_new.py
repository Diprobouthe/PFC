# tasks_new.py - New tournament automation using the automation engine

import logging
from django.db import transaction
from .models import Tournament
from .automation_engine import TournamentEngine

logger = logging.getLogger("tournaments")

def check_round_completion(tournament_id):
    """
    Main entry point for tournament automation.
    Called when matches are completed to check if round/stage/tournament is complete.
    """
    logger.info(f"🔍 DEBUG: check_round_completion called for tournament {tournament_id}")
    
    try:
        tournament = Tournament.objects.get(id=tournament_id)
        logger.info(f"🔍 DEBUG: Tournament {tournament_id} found - Format: {tournament.format}, Status: {tournament.automation_status}")
        
        # Check if automation should run
        if tournament.automation_status not in ["idle", "needs_attention"]:
            logger.info(f"Automation for tournament {tournament_id} is not idle (status: {tournament.automation_status})")
            return
        
        # Set status to processing to prevent concurrent runs
        tournament.automation_status = "processing"
        tournament.save()
        
        try:
            # Use the new automation engine
            engine = TournamentEngine(tournament)
            success = engine.process_automation()
            
            if success:
                logger.info(f"✅ Automation completed successfully for tournament {tournament_id}")
            else:
                logger.warning(f"⚠️ Automation completed with issues for tournament {tournament_id}")
                
        except Exception as e:
            logger.exception(f"Error in automation engine for tournament {tournament_id}: {e}")
            # Engine handles its own error states
            
    except Tournament.DoesNotExist:
        logger.error(f"Tournament {tournament_id} not found")
    except Exception as e:
        logger.exception(f"Error in check_round_completion for tournament {tournament_id}: {e}")


def retry_tournament_automation(tournament_id):
    """
    Retry automation for tournaments in 'needs_attention' state.
    Can be called manually from admin or scheduled task.
    """
    logger.info(f"🔄 Retrying automation for tournament {tournament_id}")
    
    try:
        tournament = Tournament.objects.get(id=tournament_id)
        
        if tournament.automation_status == "needs_attention":
            # Reset status and retry
            tournament.automation_status = "idle"
            tournament.save()
            
            # Run automation
            check_round_completion(tournament_id)
            
            logger.info(f"✅ Retry completed for tournament {tournament_id}")
        else:
            logger.warning(f"Tournament {tournament_id} is not in 'needs_attention' state (current: {tournament.automation_status})")
            
    except Tournament.DoesNotExist:
        logger.error(f"Tournament {tournament_id} not found for retry")
    except Exception as e:
        logger.exception(f"Error retrying automation for tournament {tournament_id}: {e}")


def manual_advance_stage(tournament_id):
    """
    Manually advance tournament to next stage.
    Useful for admin intervention when automation fails.
    """
    logger.info(f"🔧 Manual stage advancement for tournament {tournament_id}")
    
    try:
        tournament = Tournament.objects.get(id=tournament_id)
        engine = TournamentEngine(tournament)
        
        if engine.is_current_stage_complete():
            success = engine.advance_to_next_stage()
            if success:
                logger.info(f"✅ Manual stage advancement successful for tournament {tournament_id}")
            else:
                logger.error(f"❌ Manual stage advancement failed for tournament {tournament_id}")
        else:
            logger.warning(f"⚠️ Current stage is not complete for tournament {tournament_id}")
            
    except Tournament.DoesNotExist:
        logger.error(f"Tournament {tournament_id} not found for manual advancement")
    except Exception as e:
        logger.exception(f"Error in manual stage advancement for tournament {tournament_id}: {e}")


def manual_generate_round(tournament_id):
    """
    Manually generate next round within current stage.
    Useful for admin intervention when automation fails.
    """
    logger.info(f"🔧 Manual round generation for tournament {tournament_id}")
    
    try:
        tournament = Tournament.objects.get(id=tournament_id)
        engine = TournamentEngine(tournament)
        
        success = engine.generate_next_round()
        if success:
            logger.info(f"✅ Manual round generation successful for tournament {tournament_id}")
        else:
            logger.error(f"❌ Manual round generation failed for tournament {tournament_id}")
            
    except Tournament.DoesNotExist:
        logger.error(f"Tournament {tournament_id} not found for manual round generation")
    except Exception as e:
        logger.exception(f"Error in manual round generation for tournament {tournament_id}: {e}")


def get_tournament_status(tournament_id):
    """
    Get detailed status information for a tournament.
    Useful for debugging and admin interface.
    """
    try:
        tournament = Tournament.objects.get(id=tournament_id)
        engine = TournamentEngine(tournament)
        
        status = {
            'tournament_id': tournament_id,
            'name': tournament.name,
            'format': tournament.format,
            'automation_status': tournament.automation_status,
            'current_round': tournament.current_round_number,
            'is_active': tournament.is_active,
            'is_archived': tournament.is_archived,
            'current_stage': None,
            'stage_complete': False,
            'tournament_complete': False,
            'active_teams': 0,
            'total_teams': 0,
        }
        
        if engine.current_stage:
            status['current_stage'] = {
                'number': engine.current_stage.stage_number,
                'name': engine.current_stage.name,
                'format': engine.current_stage.format,
                'num_rounds': engine.current_stage.num_rounds_in_stage,
                'num_qualifiers': engine.current_stage.num_qualifiers,
            }
            status['stage_complete'] = engine.is_current_stage_complete()
        
        status['tournament_complete'] = engine.is_tournament_complete()
        
        # Count teams
        from .models import TournamentTeam
        status['total_teams'] = TournamentTeam.objects.filter(tournament=tournament).count()
        status['active_teams'] = TournamentTeam.objects.filter(tournament=tournament, is_active=True).count()
        
        return status
        
    except Tournament.DoesNotExist:
        return {'error': f'Tournament {tournament_id} not found'}
    except Exception as e:
        logger.exception(f"Error getting tournament status for {tournament_id}: {e}")
        return {'error': str(e)}


# Legacy function compatibility
def generate_next_round_robin_round(tournament):
    """Legacy compatibility - redirects to new system"""
    logger.info(f"Legacy round robin function called for tournament {tournament.id}")
    check_round_completion(tournament.id)

def generate_next_swiss_round(tournament, stage=None):
    """Legacy compatibility - redirects to new system"""
    logger.info(f"Legacy Swiss function called for tournament {tournament.id}")
    check_round_completion(tournament.id)

def generate_next_knockout_round(tournament):
    """Legacy compatibility - redirects to new system"""
    logger.info(f"Legacy knockout function called for tournament {tournament.id}")
    check_round_completion(tournament.id)

