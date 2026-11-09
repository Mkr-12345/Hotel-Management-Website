import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone


class Location(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(unique=True)
    country = models.CharField(max_length=80, default="India")
    is_international = models.BooleanField(default=False)
    description = models.TextField()
    image_url = models.URLField(max_length=500)
    address = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["is_international", "name"]

    def __str__(self):
        return self.name if not self.is_international else f"{self.name}, {self.country}"


class RoomType(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(unique=True)
    description = models.TextField()
    image_url = models.URLField(max_length=500)
    price_per_night = models.PositiveIntegerField(help_text="Price in rupees per night")
    max_guests = models.PositiveSmallIntegerField(default=2)
    features = models.CharField(max_length=300, blank=True, help_text="Comma separated, e.g. King bed, Minibar")
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "price_per_night"]

    def __str__(self):
        return self.name

    def feature_list(self):
        return [f.strip() for f in self.features.split(",") if f.strip()]

    def get_absolute_url(self):
        return reverse("room_detail", args=[self.slug])


class Room(models.Model):
    """A physical room in a hotel. Bookings are assigned to one of these."""

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="rooms")
    room_type = models.ForeignKey(RoomType, on_delete=models.PROTECT, related_name="rooms")
    number = models.CharField(max_length=10)
    is_active = models.BooleanField(default=True, help_text="Untick for maintenance / out of service")

    class Meta:
        ordering = ["location", "number"]
        unique_together = [("location", "number")]

    def __str__(self):
        return f"{self.location.name} #{self.number} ({self.room_type.name})"


def generate_reference():
    return "MKR" + secrets.token_hex(4).upper()


class BookingQuerySet(models.QuerySet):
    def blocking(self):
        """Bookings that currently occupy a room: confirmed ones, plus unpaid
        ones that are still inside their hold window."""
        hold_cutoff = timezone.now() - timedelta(minutes=settings.BOOKING_HOLD_MINUTES)
        return self.filter(
            Q(status=Booking.Status.CONFIRMED)
            | Q(status=Booking.Status.PENDING, created_at__gte=hold_cutoff)
        )

    def overlapping(self, check_in, check_out):
        return self.filter(check_in__lt=check_out, check_out__gt=check_in)


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting payment"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired (not paid)"

    reference = models.CharField(max_length=20, unique=True, default=generate_reference, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookings")
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="bookings")
    guest_name = models.CharField(max_length=120)
    guest_email = models.EmailField()
    guest_phone = models.CharField(max_length=20)
    guests = models.PositiveSmallIntegerField(default=1)
    check_in = models.DateField()
    check_out = models.DateField()
    nightly_rate = models.PositiveIntegerField()
    total_amount = models.PositiveIntegerField(help_text="Total in rupees")
    special_requests = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    objects = BookingQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference} – {self.guest_name}"

    def clean(self):
        if self.check_in and self.check_out and self.check_out <= self.check_in:
            raise ValidationError("Check-out must be after check-in.")

    @property
    def nights(self):
        return (self.check_out - self.check_in).days

    @property
    def location(self):
        return self.room.location

    @property
    def room_type(self):
        return self.room.room_type

    @property
    def hold_expires_at(self):
        return self.created_at + timedelta(minutes=settings.BOOKING_HOLD_MINUTES)

    @property
    def hold_expired(self):
        return self.status == self.Status.PENDING and timezone.now() > self.hold_expires_at

    @property
    def can_cancel(self):
        if self.status == self.Status.PENDING:
            return True
        return self.status == self.Status.CONFIRMED and self.check_in > timezone.localdate()

    def get_absolute_url(self):
        return reverse("booking_receipt", args=[self.reference])


class Payment(models.Model):
    class Status(models.TextChoices):
        CREATED = "created", "Created"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="payments")
    provider = models.CharField(max_length=20, default="razorpay")
    order_id = models.CharField(max_length=60, unique=True)
    payment_id = models.CharField(max_length=60, blank=True)
    signature = models.CharField(max_length=200, blank=True)
    refund_id = models.CharField(max_length=60, blank=True)
    amount = models.PositiveIntegerField(help_text="Amount in rupees")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CREATED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order_id} ({self.get_status_display()})"


class ContactMessage(models.Model):
    name = models.CharField(max_length=120)
    email = models.EmailField()
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} <{self.email}>"
