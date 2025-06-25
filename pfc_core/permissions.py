from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.auth.decorators import user_passes_test

def is_staff_or_admin(user):
    """Check if user is staff or belongs to Tournament Administrators group"""
    return user.is_staff or user.is_superuser or user.groups.filter(name='Tournament Administrators').exists()

def is_team_member(user):
    """Check if user belongs to Team Members group"""
    return user.groups.filter(name='Team Members').exists()

class StaffRequiredMixin(UserPassesTestMixin):
    """Mixin to require staff or admin permissions for class-based views"""
    def test_func(self):
        return is_staff_or_admin(self.request.user)

class TeamMemberRequiredMixin(UserPassesTestMixin):
    """Mixin to require team member permissions for class-based views"""
    def test_func(self):
        return is_team_member(self.request.user)
