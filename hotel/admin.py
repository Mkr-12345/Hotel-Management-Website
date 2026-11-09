from django.contrib import admin, messages

from . import services
from .models import Booking, ContactMessage, Location, Payment, Room, RoomType


class RoomInline(admin.TabularInline):
    model = Room
    extra = 1


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "is_international", "is_active", "room_count")
    list_filter = ("is_international", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "country")
    inlines = [RoomInline]

    @admin.display(description="Rooms")
    def room_count(self, obj):
        return obj.rooms.count()


@admin.register(RoomType)
class RoomTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "price_per_night", "max_guests", "sort_order")
    list_editable = ("price_per_night", "max_guests", "sort_order")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("__str__", "location", "room_type", "is_active")
    list_filter = ("location", "room_type", "is_active")
    list_editable = ("is_active",)


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("provider", "order_id", "payment_id", "refund_id", "amount", "status", "created_at")
    can_delete = False


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("reference", "guest_name", "room", "check_in", "check_out", "total_amount", "status", "created_at")
    list_filter = ("status", "room__location", "room__room_type", "check_in")
    search_fields = ("reference", "guest_name", "guest_email", "guest_phone")
    date_hierarchy = "check_in"
    readonly_fields = ("reference", "created_at", "confirmed_at", "cancelled_at")
    inlines = [PaymentInline]
    actions = ["cancel_and_refund"]

    @admin.action(description="Cancel selected bookings (refunds payments)")
    def cancel_and_refund(self, request, queryset):
        done = 0
        for booking in queryset:
            booking, _ = services.cancel_booking(booking, force=True)
            done += booking.status == Booking.Status.CANCELLED
        self.message_user(request, f"{done} booking(s) cancelled.", messages.SUCCESS)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("order_id", "booking", "provider", "amount", "status", "created_at")
    list_filter = ("status", "provider")
    search_fields = ("order_id", "payment_id", "booking__reference")
    readonly_fields = [f.name for f in Payment._meta.fields]


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "created_at", "is_resolved")
    list_filter = ("is_resolved",)
    list_editable = ("is_resolved",)
    search_fields = ("name", "email", "message")
