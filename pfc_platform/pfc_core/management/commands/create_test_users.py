from django.contrib.auth.models import User, Group
from django.core.management.base import BaseCommand
from teams.models import Team
import random
import string

class Command(BaseCommand):
    help = 'Create test users for different roles in the PFC platform'

    def handle(self, *args, **options):
        # Create admin user if it doesn't exist
        if not User.objects.filter(username='admin').exists():
            admin_user = User.objects.create_superuser(
                username='admin',
                email='admin@example.com',
                password='adminpassword'
            )
            self.stdout.write(self.style.SUCCESS(f'Created admin user: {admin_user.username}'))
        else:
            admin_user = User.objects.get(username='admin')
            self.stdout.write(self.style.SUCCESS(f'Admin user already exists: {admin_user.username}'))
        
        # Create staff user if it doesn't exist
        if not User.objects.filter(username='staff').exists():
            staff_user = User.objects.create_user(
                username='staff',
                email='staff@example.com',
                password='staffpassword',
                is_staff=True
            )
            self.stdout.write(self.style.SUCCESS(f'Created staff user: {staff_user.username}'))
        else:
            staff_user = User.objects.get(username='staff')
            self.stdout.write(self.style.SUCCESS(f'Staff user already exists: {staff_user.username}'))
        
        # Get or create groups
        admin_group, _ = Group.objects.get_or_create(name='Tournament Administrators')
        staff_group, _ = Group.objects.get_or_create(name='Tournament Staff')
        team_group, _ = Group.objects.get_or_create(name='Team Members')
        
        # Assign admin to Tournament Administrators group
        admin_user.groups.add(admin_group)
        
        # Assign staff to Tournament Staff group
        staff_user.groups.add(staff_group)
        
        # Create team users
        teams = Team.objects.all()
        for team in teams:
            username = f"team_{team.name.lower().replace(' ', '_')}"
            if not User.objects.filter(username=username).exists():
                team_user = User.objects.create_user(
                    username=username,
                    email=f"{username}@example.com",
                    password=team.pin,  # Use team PIN as password for simplicity
                    first_name=team.name,
                    is_staff=False
                )
                team_user.groups.add(team_group)
                self.stdout.write(self.style.SUCCESS(f'Created team user: {team_user.username} with PIN: {team.pin}'))
            else:
                team_user = User.objects.get(username=username)
                self.stdout.write(self.style.SUCCESS(f'Team user already exists: {team_user.username}'))
        
        self.stdout.write(self.style.SUCCESS('User setup completed successfully'))
