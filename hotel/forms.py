from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.validators import RegexValidator
from django.utils import timezone

from .models import ContactMessage, Location, RoomType

phone_validator = RegexValidator(r"^\+?[0-9 \-]{7,15}$", "Enter a valid phone number.")


class SignUpForm(UserCreationForm):
    first_name = forms.CharField(max_length=60, label="Full name")
    email = forms.EmailField()

    class Meta:
        model = User
        fields = ("username", "first_name", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        if commit:
            user.save()
        return user


class DateInput(forms.DateInput):
    input_type = "date"


class AvailabilityForm(forms.Form):
    location = forms.ModelChoiceField(Location.objects.filter(is_active=True), empty_label="Choose a location")
    room_type = forms.ModelChoiceField(RoomType.objects.all(), empty_label="Select room type", label="Room type")
    check_in = forms.DateField(widget=DateInput, label="Check-in date")
    check_out = forms.DateField(widget=DateInput, label="Check-out date")
    guests = forms.IntegerField(min_value=1, max_value=10, initial=2)

    MAX_NIGHTS = 30

    def clean(self):
        data = super().clean()
        check_in, check_out = data.get("check_in"), data.get("check_out")
        if check_in and check_in < timezone.localdate():
            self.add_error("check_in", "Check-in can't be in the past.")
        if check_in and check_out:
            if check_out <= check_in:
                self.add_error("check_out", "Check-out must be after check-in.")
            elif (check_out - check_in).days > self.MAX_NIGHTS:
                self.add_error("check_out", f"Online bookings are limited to {self.MAX_NIGHTS} nights.")
        room_type, guests = data.get("room_type"), data.get("guests")
        if room_type and guests and guests > room_type.max_guests:
            self.add_error("guests", f"{room_type.name} fits up to {room_type.max_guests} guests.")
        return data


class BookingForm(AvailabilityForm):
    guest_name = forms.CharField(max_length=120, label="Your name")
    guest_email = forms.EmailField(label="Your email")
    guest_phone = forms.CharField(max_length=20, label="Phone number", validators=[phone_validator])
    special_requests = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False, label="Special requests (optional)")

    field_order = [
        "guest_name", "guest_email", "guest_phone", "location", "check_in", "check_out", "room_type", "guests", "special_requests",
    ]


class ContactForm(forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ("name", "email", "message")
        labels = {"name": "Your name", "email": "Your email", "message": "Your message"}
        widgets = {"message": forms.Textarea(attrs={"rows": 5})}
