from django import forms
from django.core.exceptions import ValidationError
from .models import TournamentScenario, VoucherCode, SimpleTournament
from courts.models import CourtComplex


class SimpleTournamentCreationForm(forms.Form):
    """Ultra-simple tournament creation form"""
    
    scenario = forms.ModelChoiceField(
        queryset=TournamentScenario.objects.all(),
        widget=forms.RadioSelect,
        empty_label=None,
        help_text="Choose your tournament scenario"
    )
    
    format_type = forms.ChoiceField(
        choices=[
            ('doubles', 'Doubles (≤12 players)'),
            ('triples', 'Triples (≤18 players)')
        ],
        widget=forms.RadioSelect,
        help_text="Choose tournament format"
    )
    
    court_complex = forms.ModelChoiceField(
        queryset=CourtComplex.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text="System will auto-assign up to 3 available courts"
    )
    
    voucher_code = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter voucher code (if required)'
        }),
        help_text="Required for paid scenarios"
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Add CSS classes for styling
        self.fields['scenario'].widget.attrs.update({'class': 'form-check-input'})
        self.fields['format_type'].widget.attrs.update({'class': 'form-check-input'})
        
        # Customize scenario display
        self.fields['scenario'].queryset = TournamentScenario.objects.all().order_by('is_free', 'name')
    
    def clean(self):
        cleaned_data = super().clean()
        scenario = cleaned_data.get('scenario')
        voucher_code = cleaned_data.get('voucher_code')
        
        if not scenario:
            return cleaned_data
        
        # Check if scenario requires voucher
        if scenario.requires_voucher and not scenario.is_free:
            if not voucher_code:
                raise ValidationError("This scenario requires a voucher code.")
            
            # Validate voucher code
            try:
                voucher = VoucherCode.objects.get(
                    code=voucher_code,
                    scenario=scenario,
                    is_used=False
                )
                cleaned_data['voucher_object'] = voucher
            except VoucherCode.DoesNotExist:
                raise ValidationError("Invalid or already used voucher code for this scenario.")
        
        return cleaned_data


class VoucherGenerationForm(forms.Form):
    """Form for admins to generate voucher codes"""
    
    scenario = forms.ModelChoiceField(
        queryset=TournamentScenario.objects.filter(requires_voucher=True),
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    count = forms.IntegerField(
        min_value=1,
        max_value=100,
        initial=10,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        help_text="Number of vouchers to generate (1-100)"
    )
    
    prefix = forms.CharField(
        max_length=5,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Optional prefix (e.g., MAD)'
        }),
        help_text="Optional prefix for voucher codes"
    )


class TournamentScenarioForm(forms.ModelForm):
    """Form for creating/editing tournament scenarios"""
    
    class Meta:
        model = TournamentScenario
        fields = [
            'name', 'display_name', 'description', 'is_free', 'requires_voucher',
            'max_doubles_players', 'max_triples_players', 'tournament_type',
            'num_rounds', 'matches_per_team', 'draft_type'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'display_name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'max_doubles_players': forms.NumberInput(attrs={'class': 'form-control'}),
            'max_triples_players': forms.NumberInput(attrs={'class': 'form-control'}),
            'num_rounds': forms.NumberInput(attrs={'class': 'form-control'}),
            'matches_per_team': forms.NumberInput(attrs={'class': 'form-control'}),
            'tournament_type': forms.Select(attrs={'class': 'form-control'}),
            'draft_type': forms.Select(attrs={'class': 'form-control'}),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        is_free = cleaned_data.get('is_free')
        requires_voucher = cleaned_data.get('requires_voucher')
        
        # Logic validation
        if is_free and requires_voucher:
            raise ValidationError("A scenario cannot be both free and require a voucher.")
        
        if not is_free and not requires_voucher:
            raise ValidationError("A paid scenario must require a voucher.")
        
        return cleaned_data

