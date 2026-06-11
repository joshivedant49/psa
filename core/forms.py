from django import forms
from .models import FeeStructures

class FeeStructureForm(forms.ModelForm):
    class Meta:
        model = FeeStructures
        fields = '__all__'