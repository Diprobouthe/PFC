from django import forms
from .models import TournamentScenario, VoucherCode
from court_management.models import CourtComplex


class TournamentCreationForm(forms.Form):
    """Simple tournament creation form."""
    
    scenario = forms.ModelChoiceField(
        queryset=TournamentScenario.objects.filter(is_active=True),
        widget=forms.RadioSelect,
        empty_label=None,
        help_text="Choose your tournament scenario"
    )
    
    format = forms.ChoiceField(
        choices=[
            ('doubles', 'Doubles (≤12 players)'),
            ('triples', 'Triples (≤18 players)'),
        ],
        widget=forms.RadioSelect,
        initial='doubles',
        help_text="Select tournament format"
    )
    
    court_complex = forms.ModelChoiceField(
        queryset=CourtComplex.objects.all(),
        help_text="Select court complex (system will auto-assign up to 5 available courts)"
    )
    
    voucher_code = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Enter voucher code',
            'class': 'form-control',
            'style': 'text-transform: uppercase;'
        }),
        help_text="Required for premium scenarios"
    )
    
    creator_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Your name (optional)',
            'class': 'form-control'
        }),
        help_text="Optional: Your name for tournament records"
    )
    
    def clean(self):
        cleaned_data = super().clean()
        scenario = cleaned_data.get('scenario')
        voucher_code = cleaned_data.get('voucher_code')
        
        if scenario and not scenario.is_free:
            if not voucher_code:
                raise forms.ValidationError("Voucher code is required for this scenario.")
            
            # Validate voucher
            try:
                voucher = VoucherCode.objects.get(
                    code=voucher_code.upper(),
                    scenario=scenario
                )
                if not voucher.is_valid():
                    raise forms.ValidationError("Voucher code has already been used or expired.")
                
                # Store the validated voucher code in uppercase
                cleaned_data['voucher_code'] = voucher_code.upper()
                
            except VoucherCode.DoesNotExist:
                raise forms.ValidationError("Invalid voucher code for this scenario.")
        
        return cleaned_data
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Add CSS classes
        for field_name, field in self.fields.items():
            if field_name not in ['scenario', 'format']:
                field.widget.attrs['class'] = 'form-control'

