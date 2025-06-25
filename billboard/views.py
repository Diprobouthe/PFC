from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.utils import timezone
from datetime import timedelta
import json

from .models import BillboardEntry, BillboardResponse, BillboardSettings
from .forms import BillboardEntryForm, BillboardResponseForm, QuickResponseForm
from teams.models import Team


def team_search_api(request):
    """API endpoint for team search functionality"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse({'teams': []})
    
    # Search teams by name (case-insensitive, contains)
    teams = Team.objects.filter(
        name__icontains=query
    ).order_by('name')[:10]  # Limit to 10 results
    
    team_data = []
    for team in teams:
        team_data.append({
            'id': team.id,
            'name': team.name,
            'pin': team.pin  # Include PIN for verification later
        })
    
    return JsonResponse({'teams': team_data})


@csrf_exempt
@require_http_methods(["POST"])
def respond_to_match(request, entry_id):
    """Handle tournament match responses with team PIN verification"""
    try:
        entry = BillboardEntry.objects.get(id=entry_id)
        
        # Parse JSON data
        data = json.loads(request.body)
        team_pin = data.get('team_pin', '').strip()
        opponent_team = data.get('opponent_team', '').strip()
        
        print(f"DEBUG: Entry ID: {entry_id}")
        print(f"DEBUG: Team PIN received: '{team_pin}'")
        print(f"DEBUG: Opponent team: '{opponent_team}'")
        
        if not team_pin or not opponent_team:
            return JsonResponse({
                'success': False,
                'message': 'Team PIN and opponent team are required'
            })
        
        # Verify that the team PIN belongs to the specified opponent team
        try:
            team = Team.objects.get(name=opponent_team, pin=team_pin)
            print(f"DEBUG: Team found: {team.name} with PIN: {team.pin}")
        except Team.DoesNotExist:
            print(f"DEBUG: No team found with name '{opponent_team}' and PIN '{team_pin}'")
            # Let's check what teams exist
            teams = Team.objects.filter(name=opponent_team)
            print(f"DEBUG: Teams with name '{opponent_team}': {[t.pin for t in teams]}")
            return JsonResponse({
                'success': False,
                'message': 'Invalid team PIN. Only the specified opponent team can accept this match.'
            })
        
        # Check if this team has already responded
        existing_response = BillboardResponse.objects.filter(
            entry=entry,
            codename=f"TEAM_{team.name}"
        ).first()
        
        if existing_response:
            return JsonResponse({
                'success': False,
                'message': 'Your team has already responded to this match appointment.'
            })
        
        # Create the response
        response = BillboardResponse.objects.create(
            entry=entry,
            codename=f"TEAM_{team.name}",  # Use team name as codename
            response_type='ACCEPTING'
        )
        
        # Mark the entry as confirmed
        entry.is_confirmed = True
        entry.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Match confirmed! {team.name} has agreed to the appointment.',
            'team_name': team.name
        })
        
    except BillboardEntry.DoesNotExist:
        print(f"DEBUG: BillboardEntry with ID {entry_id} not found")
        return JsonResponse({
            'success': False,
            'message': 'Match appointment not found'
        })
    except json.JSONDecodeError as e:
        print(f"DEBUG: JSON decode error: {e}")
        return JsonResponse({
            'success': False,
            'message': 'Invalid request data'
        })
    except Exception as e:
        print(f"DEBUG: Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': 'An error occurred while processing your request'
        })


class BillboardListView(ListView):
    """Main Billboard view showing all active entries"""
    model = BillboardEntry
    template_name = 'billboard/billboard_list.html'
    context_object_name = 'entries'
    paginate_by = 20
    
    def get_queryset(self):
        # Get active entries from the last 24 hours
        cutoff_time = timezone.now() - timedelta(hours=24)
        return BillboardEntry.objects.filter(
            is_active=True,
            created_at__gte=cutoff_time
        ).select_related('court_complex').prefetch_related('responses')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['settings'] = BillboardSettings.get_settings()
        
        # Group entries by action type for better display
        entries = context['entries']
        context['at_courts'] = [e for e in entries if e.action_type == 'AT_COURTS']
        context['going_to_courts'] = [e for e in entries if e.action_type == 'GOING_TO_COURTS']
        context['looking_for_match'] = [e for e in entries if e.action_type == 'LOOKING_FOR_MATCH']
        
        return context


class BillboardCreateView(CreateView):
    """Create new Billboard entry"""
    model = BillboardEntry
    form_class = BillboardEntryForm
    template_name = 'billboard/billboard_create.html'
    success_url = reverse_lazy('billboard:list')
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs
    
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Your entry has been posted to the Billboard!')
        return response
    
    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)


class BillboardUpdateView(UpdateView):
    """Edit existing Billboard entry (only by owner)"""
    model = BillboardEntry
    form_class = BillboardEntryForm
    template_name = 'billboard/billboard_edit.html'
    success_url = reverse_lazy('billboard:list')
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs
    
    def get_queryset(self):
        # Users can only edit their own entries
        return BillboardEntry.objects.filter(is_active=True)
    
    def form_valid(self, form):
        # Verify ownership
        if form.instance.codename != form.cleaned_data['codename']:
            messages.error(self.request, 'You can only edit your own entries.')
            return self.form_invalid(form)
        
        response = super().form_valid(form)
        messages.success(self.request, 'Your entry has been updated!')
        return response


class BillboardDeleteView(DeleteView):
    """Delete Billboard entry (only by owner)"""
    model = BillboardEntry
    template_name = 'billboard/billboard_confirm_delete.html'
    success_url = reverse_lazy('billboard:list')
    
    def get_queryset(self):
        return BillboardEntry.objects.filter(is_active=True)
    
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        # Soft delete
        self.object.is_active = False
        self.object.save()
        messages.success(request, 'Your entry has been removed from the Billboard.')
        return redirect(self.success_url)


@require_http_methods(["POST"])
def respond_to_entry(request, entry_id):
    """Handle responses to Billboard entries"""
    entry = get_object_or_404(BillboardEntry, id=entry_id, is_active=True)
    
    if request.content_type == 'application/json':
        # AJAX request
        try:
            data = json.loads(request.body)
            form = QuickResponseForm(data, entry=entry)
            
            if form.is_valid():
                codename = form.cleaned_data['codename']
                
                # Determine response type based on entry action
                if entry.action_type == 'AT_COURTS':
                    response_type = 'JOINING'
                    response_text = "I'm there too!"
                elif entry.action_type == 'GOING_TO_COURTS':
                    response_type = 'JOINING'
                    response_text = "I'll come too!"
                elif entry.action_type == 'LOOKING_FOR_MATCH':
                    response_type = 'ACCEPTING'
                    response_text = "We accept!"
                else:
                    response_type = 'JOINING'
                    response_text = "Joined"
                
                # Create response
                response = BillboardResponse.objects.create(
                    entry=entry,
                    codename=codename,
                    response_type=response_type
                )
                
                return JsonResponse({
                    'success': True,
                    'message': f'{codename} - {response_text}',
                    'response_count': entry.get_response_count()
                })
            else:
                return JsonResponse({
                    'success': False,
                    'errors': form.errors
                })
        
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'})
    
    else:
        # Regular form submission
        form = BillboardResponseForm(request.POST, entry=entry)
        
        if form.is_valid():
            response = form.save(commit=False)
            response.entry = entry
            
            # Set response type based on entry action
            if entry.action_type == 'LOOKING_FOR_MATCH':
                response.response_type = 'ACCEPTING'
            else:
                response.response_type = 'JOINING'
            
            response.save()
            messages.success(request, 'Your response has been recorded!')
        else:
            for error in form.errors.values():
                messages.error(request, error)
    
    return redirect('billboard:list')


def entry_detail(request, entry_id):
    """Detailed view of a Billboard entry"""
    entry = get_object_or_404(BillboardEntry, id=entry_id, is_active=True)
    responses = entry.get_responses()
    
    context = {
        'entry': entry,
        'responses': responses,
        'response_form': BillboardResponseForm(entry=entry),
        'can_respond': not entry.is_expired(),
    }
    
    return render(request, 'billboard/billboard_detail.html', context)


def get_entry_responses(request, entry_id):
    """AJAX endpoint to get current responses for an entry"""
    entry = get_object_or_404(BillboardEntry, id=entry_id, is_active=True)
    responses = entry.get_responses()
    
    response_data = []
    for response in responses:
        response_data.append({
            'codename': response.codename,
            'response_text': response.get_response_text(),
            'created_at': response.created_at.strftime('%H:%M')
        })
    
    return JsonResponse({
        'responses': response_data,
        'count': len(response_data)
    })


def billboard_stats(request):
    """Statistics view for Billboard activity"""
    settings = BillboardSettings.get_settings()
    
    # Get stats for the last 24 hours
    cutoff_time = timezone.now() - timedelta(hours=24)
    
    stats = {
        'total_entries': BillboardEntry.objects.filter(
            is_active=True,
            created_at__gte=cutoff_time
        ).count(),
        'at_courts_count': BillboardEntry.objects.filter(
            is_active=True,
            action_type='AT_COURTS',
            created_at__gte=cutoff_time
        ).count(),
        'going_to_courts_count': BillboardEntry.objects.filter(
            is_active=True,
            action_type='GOING_TO_COURTS',
            created_at__gte=cutoff_time
        ).count(),
        'looking_for_match_count': BillboardEntry.objects.filter(
            is_active=True,
            action_type='LOOKING_FOR_MATCH',
            created_at__gte=cutoff_time
        ).count(),
        'total_responses': BillboardResponse.objects.filter(
            created_at__gte=cutoff_time
        ).count(),
    }
    
    context = {
        'stats': stats,
        'settings': settings,
    }
    
    return render(request, 'billboard/billboard_stats.html', context)

