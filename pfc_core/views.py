from django.shortcuts import render
from django.contrib.auth.decorators import login_required

def home(request):
    """View for the home page"""
    return render(request, 'home.html')

@login_required
def dashboard(request):
    """View for the user dashboard"""
    return render(request, 'dashboard.html')
