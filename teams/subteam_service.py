"""
Subteam Management Service

This module provides intelligent subteam creation and management functionality
for the PFC platform without modifying existing tournament logic.
"""

from django.db import transaction
from teams.models import Team, Player
from tournaments.models import Tournament, TournamentTeam


class SubteamManager:
    """
    Smart subteam management service that handles:
    - Detection of existing subteams
    - Automatic subteam creation
    - Player assignment validation
    - Tournament registration
    """
    
    SUBTEAM_TYPES = {
        'triplet': 3,
        'doublette': 2,
        'tete_a_tete': 1,
    }
    
    def __init__(self, parent_team):
        self.parent_team = parent_team
    
    def get_existing_subteams(self, subteam_type=None):
        """Get existing subteams for the parent team"""
        queryset = Team.objects.filter(
            parent_team=self.parent_team,
            is_subteam=True
        )
        
        if subteam_type:
            queryset = queryset.filter(subteam_type=subteam_type)
        
        return queryset.order_by('name')
    
    def get_subteam_suggestions(self, tournament_requirements):
        """
        Analyze tournament requirements and suggest subteam configurations
        
        Args:
            tournament_requirements: dict with format restrictions
            e.g., {'allowed_formats': ['triplet'], 'max_teams_per_parent': 3}
        
        Returns:
            dict with suggestions and existing subteams
        """
        suggestions = {
            'existing_subteams': {},
            'can_reuse': {},
            'need_to_create': {},
            'player_availability': {}
        }
        
        allowed_formats = tournament_requirements.get('allowed_formats', ['triplet', 'doublette', 'tete_a_tete'])
        
        for format_type in allowed_formats:
            existing = self.get_existing_subteams(format_type)
            suggestions['existing_subteams'][format_type] = list(existing)
            suggestions['can_reuse'][format_type] = existing.count()
        
        # Check player availability
        total_players = self.parent_team.players.count()
        suggestions['player_availability'] = {
            'total_players': total_players,
            'max_triplets': total_players // 3,
            'max_doublettes': total_players // 2,
            'max_tete_a_tete': total_players
        }
        
        return suggestions
    
    def validate_subteam_request(self, subteam_specs):
        """
        Validate if requested subteams can be created
        
        Args:
            subteam_specs: list of dicts like [{'type': 'triplet', 'count': 2}]
        
        Returns:
            dict with validation results
        """
        validation = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'total_players_needed': 0,
            'available_players': self.parent_team.players.count()
        }
        
        total_needed = 0
        for spec in subteam_specs:
            subteam_type = spec['type']
            count = spec['count']
            
            if subteam_type not in self.SUBTEAM_TYPES:
                validation['errors'].append(f"Invalid subteam type: {subteam_type}")
                validation['valid'] = False
                continue
            
            players_per_subteam = self.SUBTEAM_TYPES[subteam_type]
            total_needed += players_per_subteam * count
        
        validation['total_players_needed'] = total_needed
        
        if total_needed > validation['available_players']:
            validation['errors'].append(
                f"Not enough players: need {total_needed}, have {validation['available_players']}"
            )
            validation['valid'] = False
        
        return validation
    
    def get_next_subteam_name(self, subteam_type):
        """Generate the next sequential subteam name"""
        existing_count = self.get_existing_subteams(subteam_type).count()
        next_number = existing_count + 1
        
        type_display = subteam_type.replace('_', '-').title()
        return f"{self.parent_team.name} - {type_display} {next_number}"
    
    @transaction.atomic
    def create_subteams(self, subteam_specs, auto_register_tournament=None):
        """
        Create subteams based on specifications
        
        Args:
            subteam_specs: list of dicts like [{'type': 'triplet', 'count': 2, 'reuse_existing': False}]
            auto_register_tournament: Tournament object to auto-register subteams
        
        Returns:
            dict with created/reused subteams and results
        """
        result = {
            'success': True,
            'created_subteams': [],
            'reused_subteams': [],
            'registered_teams': [],
            'errors': []
        }
        
        try:
            # Validate first
            validation = self.validate_subteam_request(subteam_specs)
            if not validation['valid']:
                result['success'] = False
                result['errors'] = validation['errors']
                return result
            
            for spec in subteam_specs:
                subteam_type = spec['type']
                count = spec['count']
                reuse_existing = spec.get('reuse_existing', True)
                
                existing_subteams = list(self.get_existing_subteams(subteam_type))
                
                teams_to_register = []
                
                if reuse_existing and existing_subteams:
                    # Reuse existing subteams first
                    reuse_count = min(count, len(existing_subteams))
                    for i in range(reuse_count):
                        subteam = existing_subteams[i]
                        result['reused_subteams'].append(subteam)
                        teams_to_register.append(subteam)
                    
                    # Create additional if needed
                    remaining_count = count - reuse_count
                else:
                    remaining_count = count
                
                # Create new subteams
                for i in range(remaining_count):
                    subteam_name = self.get_next_subteam_name(subteam_type)
                    
                    subteam = Team.objects.create(
                        name=subteam_name,
                        parent_team=self.parent_team,
                        is_subteam=True,
                        subteam_type=subteam_type
                    )
                    
                    result['created_subteams'].append(subteam)
                    teams_to_register.append(subteam)
                
                # Auto-register to tournament if specified
                if auto_register_tournament:
                    for team in teams_to_register:
                        tournament_team, created = TournamentTeam.objects.get_or_create(
                            tournament=auto_register_tournament,
                            team=team
                        )
                        if created:
                            result['registered_teams'].append(team)
        
        except Exception as e:
            result['success'] = False
            result['errors'].append(f"Error creating subteams: {str(e)}")
        
        return result
    
    def get_subteam_registration_options(self, tournament):
        """
        Get intelligent registration options for a tournament
        
        Returns options for reusing existing subteams vs creating new ones
        """
        # Get tournament format restrictions
        tournament_formats = self._get_tournament_allowed_formats(tournament)
        team_size = self.parent_team.players.count()
        
        options = {
            'tournament': tournament,
            'parent_team': self.parent_team,
            'format_options': {},
            'recommendations': [],
            'can_register_as_full_team': False,
            'has_subteam_options': False
        }
        
        # Check if team can register as full team
        options['can_register_as_full_team'] = self._can_register_as_full_team(tournament, team_size)
        
        # Calculate subteam options for each allowed format
        for format_type in tournament_formats:
            players_per_subteam = self.SUBTEAM_TYPES[format_type]
            existing = self.get_existing_subteams(format_type)
            max_possible = team_size // players_per_subteam
            
            # Only include formats where team can create at least one subteam
            if max_possible > 0:
                format_options = []
                
                # Option 1: Register as full team (if allowed and team size fits)
                if options['can_register_as_full_team'] and team_size >= players_per_subteam:
                    format_options.append({
                        'type': 'full_team',
                        'count': 1,
                        'players': team_size,
                        'description': f"Register as 1 full team ({team_size} players)"
                    })
                
                # Option 2+: Create multiple subteams
                for count in range(1, max_possible + 1):
                    remaining_players = team_size - (count * players_per_subteam)
                    description = f"Create {count} {format_type}{'s' if count > 1 else ''} ({count * players_per_subteam} players)"
                    
                    if remaining_players > 0:
                        description += f" + {remaining_players} unused player{'s' if remaining_players > 1 else ''}"
                    
                    format_options.append({
                        'type': 'subteams',
                        'count': count,
                        'players': count * players_per_subteam,
                        'remaining': remaining_players,
                        'description': description
                    })
                
                # Only include this format if there are multiple options
                if len(format_options) > 1:
                    options['format_options'][format_type] = {
                        'existing_count': existing.count(),
                        'existing_teams': list(existing),
                        'max_possible': max_possible,
                        'players_per_team': players_per_subteam,
                        'options': format_options
                    }
                    options['has_subteam_options'] = True
                    
                    # Generate recommendations
                    if existing.count() > 0:
                        options['recommendations'].append({
                            'type': 'reuse',
                            'format': format_type,
                            'message': f"You have {existing.count()} existing {format_type}(s) that can be reused"
                        })
        
        return options
    
    def _get_tournament_allowed_formats(self, tournament):
        """Get allowed formats for tournament"""
        # Check tournament model for format restrictions
        if hasattr(tournament, 'play_format'):
            play_format = tournament.play_format.lower()
            if 'triplet' in play_format and 'doublette' not in play_format and 'tete' not in play_format:
                return ['triplet']
            elif 'doublette' in play_format and 'triplet' not in play_format and 'tete' not in play_format:
                return ['doublette']
            elif ('tete' in play_format or 'individual' in play_format) and 'triplet' not in play_format and 'doublette' not in play_format:
                return ['tete_a_tete']
            else:
                # Mixed formats - allow all
                return ['triplet', 'doublette', 'tete_a_tete']
        
        # Default to all formats if not specified
        return ['triplet', 'doublette', 'tete_a_tete']
    
    def _can_register_as_full_team(self, tournament, team_size):
        """Check if team can register as a single full team"""
        # For now, allow full team registration for any size
        # This can be enhanced with tournament-specific rules
        return team_size >= 1


def get_subteam_manager(team):
    """Factory function to get a SubteamManager for a team"""
    return SubteamManager(team)


def get_tournament_subteam_options(team, tournament):
    """
    Convenience function to get subteam options for tournament registration
    """
    manager = get_subteam_manager(team)
    return manager.get_subteam_registration_options(tournament)


def create_tournament_subteams(team, tournament, subteam_specs):
    """
    Convenience function to create and register subteams for a tournament
    """
    manager = get_subteam_manager(team)
    return manager.create_subteams(subteam_specs, auto_register_tournament=tournament)

