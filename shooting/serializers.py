"""
DRF Serializers for Shot Accuracy Tracker API
"""

from rest_framework import serializers
from django.contrib.auth.models import User
from .models import ShotSession, ShotEvent, Achievement, EarnedAchievement


class AchievementSerializer(serializers.ModelSerializer):
    """Serializer for Achievement model"""
    
    class Meta:
        model = Achievement
        fields = ['code', 'name', 'description', 'threshold', 'icon', 'color']


class EarnedAchievementSerializer(serializers.ModelSerializer):
    """Serializer for EarnedAchievement with achievement details"""
    
    achievement = AchievementSerializer(read_only=True)
    
    class Meta:
        model = EarnedAchievement
        fields = ['achievement', 'earned_at']


class ShotEventSerializer(serializers.ModelSerializer):
    """Serializer for ShotEvent model"""
    
    class Meta:
        model = ShotEvent
        fields = ['id', 'idx', 'is_hit', 'timestamp']
        read_only_fields = ['id', 'idx', 'timestamp']


class ShotSessionSerializer(serializers.ModelSerializer):
    """Serializer for ShotSession model"""
    
    hit_rate = serializers.ReadOnlyField()
    hit_percentage = serializers.ReadOnlyField()
    events = ShotEventSerializer(many=True, read_only=True)
    earned_achievements = EarnedAchievementSerializer(many=True, read_only=True)
    
    class Meta:
        model = ShotSession
        fields = [
            'id', 'mode', 'match_id', 'inning', 'started_at', 'ended_at',
            'total_shots', 'total_hits', 'best_streak', 'current_streak',
            'hit_rate', 'hit_percentage', 'is_active', 'events', 'earned_achievements'
        ]
        read_only_fields = [
            'id', 'started_at', 'ended_at', 'total_shots', 'total_hits',
            'best_streak', 'current_streak', 'hit_rate', 'hit_percentage'
        ]
    
    def validate(self, data):
        """Validate session data according to business rules"""
        mode = data.get('mode')
        match_id = data.get('match_id')
        
        if mode == 'ingame' and not match_id:
            raise serializers.ValidationError("match_id is required when mode is 'ingame'")
        
        if mode == 'practice' and match_id:
            raise serializers.ValidationError("match_id should not be set when mode is 'practice'")
        
        return data


class ShotSessionCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new shot sessions"""
    
    class Meta:
        model = ShotSession
        fields = ['mode', 'match_id', 'inning']
    
    def validate(self, data):
        """Validate session creation data"""
        mode = data.get('mode')
        match_id = data.get('match_id')
        
        if mode == 'ingame' and not match_id:
            raise serializers.ValidationError("match_id is required when mode is 'ingame'")
        
        if mode == 'practice' and match_id:
            raise serializers.ValidationError("match_id should not be set when mode is 'practice'")
        
        return data
    
    def create(self, validated_data):
        """Create a new shot session"""
        # Add the current user from the request context
        user = self.context['request'].user
        validated_data['user'] = user
        return super().create(validated_data)


class ShotEventCreateSerializer(serializers.Serializer):
    """Serializer for creating shot events"""
    
    is_hit = serializers.BooleanField()
    
    def validate_is_hit(self, value):
        """Validate is_hit field"""
        if not isinstance(value, bool):
            raise serializers.ValidationError("is_hit must be a boolean value")
        return value


class SessionSummarySerializer(serializers.Serializer):
    """Serializer for session summary responses"""
    
    total_shots = serializers.IntegerField()
    total_hits = serializers.IntegerField()
    current_streak = serializers.IntegerField()
    best_streak = serializers.IntegerField()
    hit_rate = serializers.FloatField()
    unlocked = AchievementSerializer(many=True, required=False)
    
    def to_representation(self, instance):
        """Custom representation for session summary"""
        if isinstance(instance, dict):
            # Handle dict input from business logic
            return {
                'total_shots': instance.get('session').total_shots,
                'total_hits': instance.get('session').total_hits,
                'current_streak': instance.get('session').current_streak,
                'best_streak': instance.get('session').best_streak,
                'hit_rate': instance.get('session').hit_rate,
                'unlocked': AchievementSerializer(
                    instance.get('unlocked_achievements', []), 
                    many=True
                ).data
            }
        else:
            # Handle ShotSession model instance
            return {
                'total_shots': instance.total_shots,
                'total_hits': instance.total_hits,
                'current_streak': instance.current_streak,
                'best_streak': instance.best_streak,
                'hit_rate': instance.hit_rate,
                'unlocked': []
            }


class SessionListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for session lists"""
    
    hit_percentage = serializers.ReadOnlyField()
    duration = serializers.SerializerMethodField()
    
    class Meta:
        model = ShotSession
        fields = [
            'id', 'mode', 'match_id', 'started_at', 'ended_at',
            'total_shots', 'total_hits', 'hit_percentage', 
            'best_streak', 'is_active', 'duration'
        ]
    
    def get_duration(self, obj):
        """Calculate session duration"""
        if obj.ended_at:
            duration = obj.ended_at - obj.started_at
            total_seconds = int(duration.total_seconds())
            
            if total_seconds < 60:
                return f"{total_seconds}s"
            elif total_seconds < 3600:
                minutes = total_seconds // 60
                return f"{minutes}m"
            else:
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                return f"{hours}h {minutes}m"
        return "Active"


class UserStatsSerializer(serializers.Serializer):
    """Serializer for user shooting statistics"""
    
    total_sessions = serializers.IntegerField()
    total_shots = serializers.IntegerField()
    total_hits = serializers.IntegerField()
    overall_hit_rate = serializers.FloatField()
    best_streak_ever = serializers.IntegerField()
    achievements_count = serializers.IntegerField()
    recent_sessions = SessionListSerializer(many=True)
    
    def to_representation(self, instance):
        """Custom representation for user stats"""
        return {
            'total_sessions': instance['total_sessions'],
            'total_shots': instance['total_shots'],
            'total_hits': instance['total_hits'],
            'overall_hit_rate': instance['overall_hit_rate'],
            'best_streak_ever': instance['best_streak_ever'],
            'achievements_count': instance['achievements_count'],
            'recent_sessions': SessionListSerializer(
                instance['recent_sessions'], 
                many=True
            ).data
        }
