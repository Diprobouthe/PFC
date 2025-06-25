from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from teams.models import Player
import json

@csrf_exempt
@require_http_methods(["POST"])
def player_lookup_api(request):
    """
    API endpoint to look up player name by codename
    Used by the player codename autocomplete system
    """
    try:
        codename = request.POST.get('codename', '').strip().upper()
        
        if not codename:
            return JsonResponse({
                'success': False,
                'error': 'Codename is required'
            })
        
        if len(codename) != 6:
            return JsonResponse({
                'success': False,
                'error': 'Codename must be 6 characters'
            })
        
        # Look up player by codename
        try:
            player = Player.objects.get(name=codename)
            return JsonResponse({
                'success': True,
                'player_name': player.name,
                'codename': codename
            })
        except Player.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Player not found'
            })
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        })

