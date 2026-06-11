from django import forms
from .models import Enquiry


class EnquiryForm(forms.ModelForm):
    class Meta:
        model  = Enquiry
        fields = ['full_name', 'phone', 'email', 'sport', 'age', 'message']

    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '').strip()
        digits = ''.join(filter(str.isdigit, phone))
        if len(digits) < 10:
            raise forms.ValidationError("Please enter a valid phone number.")
        return phone

    def clean_age(self):
        age = self.cleaned_data.get('age')
        if age is not None and (age < 4 or age > 80):
            raise forms.ValidationError("Age must be between 4 and 80.")
        return age
