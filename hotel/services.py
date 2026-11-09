"""Business logic kept out of the views: availability, payments, emails."""
import hashlib
import hmac
import logging
import secrets

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from .models import Booking, Payment, Room

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- availability
def free_rooms(location, room_type, check_in, check_out):
    """Active rooms of this type at this location with no overlapping booking."""
    busy = Booking.objects.blocking().overlapping(check_in, check_out).values("room_id")
    return Room.objects.filter(location=location, room_type=room_type, is_active=True).exclude(id__in=busy)


def availability_count(location, room_type, check_in, check_out):
    return free_rooms(location, room_type, check_in, check_out).count()


class NoRoomAvailable(Exception):
    pass


@transaction.atomic
def create_booking(*, user, location, room_type, check_in, check_out, **guest_details):
    # Lock the candidate rooms so two people can't grab the last room at once.
    candidates = list(
        Room.objects.select_for_update()
        .filter(location=location, room_type=room_type, is_active=True)
        .values_list("id", flat=True)
    )
    room = free_rooms(location, room_type, check_in, check_out).filter(id__in=candidates).first()
    if room is None:
        raise NoRoomAvailable
    nights = (check_out - check_in).days
    return Booking.objects.create(
        user=user,
        room=room,
        check_in=check_in,
        check_out=check_out,
        nightly_rate=room_type.price_per_night,
        total_amount=room_type.price_per_night * nights,
        **guest_details,
    )


def expire_stale_bookings():
    """Mark unpaid bookings whose hold has run out as expired."""
    stale = Booking.objects.filter(status=Booking.Status.PENDING).exclude(
        id__in=Booking.objects.blocking().values("id")
    )
    return stale.update(status=Booking.Status.EXPIRED)


# -------------------------------------------------------------------- payments
def razorpay_client():
    import razorpay

    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def create_payment_order(booking):
    """Create (or reuse) a payment order for a pending booking."""
    existing = booking.payments.filter(status=Payment.Status.CREATED, amount=booking.total_amount).first()
    if existing:
        return existing
    if settings.PAYMENT_DEMO_MODE:
        order_id = "demo_order_" + secrets.token_hex(8)
        provider = "demo"
    else:
        order = razorpay_client().order.create(
            {
                "amount": booking.total_amount * 100,  # paise
                "currency": "INR",
                "receipt": booking.reference,
                "notes": {"booking": booking.reference},
            }
        )
        order_id = order["id"]
        provider = "razorpay"
    return Payment.objects.create(booking=booking, provider=provider, order_id=order_id, amount=booking.total_amount)


def verify_razorpay_signature(order_id, payment_id, signature):
    """Razorpay signs '<order_id>|<payment_id>' with your key secret (HMAC-SHA256)."""
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def verify_webhook_signature(body: bytes, signature):
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        return False
    expected = hmac.new(settings.RAZORPAY_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


@transaction.atomic
def mark_paid(payment, payment_id, signature=""):
    """Record a successful payment and confirm the booking. Safe to call twice."""
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    booking = payment.booking
    if payment.status == Payment.Status.PAID:
        return booking
    payment.payment_id = payment_id
    payment.signature = signature
    payment.status = Payment.Status.PAID
    payment.save()
    if booking.status == Booking.Status.CANCELLED or (
        booking.status != Booking.Status.CONFIRMED and not _secure_room(booking)
    ):
        # Paid after the hold ran out and the room was taken: refund automatically.
        booking, _ = cancel_booking(booking, force=True)
        return booking
    first_confirmation = booking.status != Booking.Status.CONFIRMED
    booking.status = Booking.Status.CONFIRMED
    booking.confirmed_at = timezone.now()
    booking.save(update_fields=["status", "confirmed_at"])
    if first_confirmation:
        transaction.on_commit(lambda: send_booking_email(booking, "confirmed"))
    return booking


@transaction.atomic
def cancel_booking(booking, force=False):
    """Cancel a booking and refund any successful payment."""
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    if not force and not booking.can_cancel:
        return booking, False
    refunded = False
    for payment in booking.payments.filter(status=Payment.Status.PAID):
        if payment.provider == "razorpay":
            try:
                refund = razorpay_client().payment.refund(payment.payment_id, {"amount": payment.amount * 100})
                payment.refund_id = refund.get("id", "")
            except Exception:  # keep the booking cancellable; staff can refund from the Razorpay dashboard
                logger.exception("Razorpay refund failed for %s", payment.payment_id)
                continue
        else:
            payment.refund_id = "demo_refund_" + secrets.token_hex(6)
        payment.status = Payment.Status.REFUNDED
        payment.save()
        refunded = True
    was_confirmed = booking.status == Booking.Status.CONFIRMED or refunded
    booking.status = Booking.Status.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.save(update_fields=["status", "cancelled_at"])
    if was_confirmed:
        transaction.on_commit(lambda: send_booking_email(booking, "cancelled"))
    return booking, refunded


def _secure_room(booking):
    """Make sure the booking still owns a free room; move it to another free
    room of the same type if its original one was taken meanwhile."""
    clash = (
        Booking.objects.blocking()
        .overlapping(booking.check_in, booking.check_out)
        .filter(room=booking.room)
        .exclude(pk=booking.pk)
        .exists()
    )
    if not clash:
        return True
    room = free_rooms(booking.room.location, booking.room.room_type, booking.check_in, booking.check_out).first()
    if room is None:
        return False
    booking.room = room
    booking.save(update_fields=["room"])
    return True


# ---------------------------------------------------------------------- emails
def send_booking_email(booking, kind):
    subject = {
        "confirmed": f"Booking confirmed – {booking.reference} | MKR Hotels",
        "cancelled": f"Booking cancelled – {booking.reference} | MKR Hotels",
    }[kind]
    body = render_to_string(f"hotel/emails/booking_{kind}.txt", {"booking": booking})
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [booking.guest_email])
    except Exception:
        logger.exception("Could not send %s email for %s", kind, booking.reference)
