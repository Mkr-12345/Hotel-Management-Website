import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import services
from .forms import AvailabilityForm, BookingForm, ContactForm, SignUpForm
from .models import Booking, Location, Payment, RoomType

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ site pages
def home(request):
    return render(request, "hotel/home.html", {
        "room_types": RoomType.objects.all()[:3],
        "nav": "home",
    })


def rooms(request):
    return render(request, "hotel/rooms.html", {"room_types": RoomType.objects.all(), "nav": "rooms"})


def room_detail(request, slug):
    room_type = get_object_or_404(RoomType, slug=slug)
    locations = Location.objects.filter(is_active=True, rooms__room_type=room_type, rooms__is_active=True).distinct()
    return render(request, "hotel/room_detail.html", {"room": room_type, "locations": locations, "nav": "rooms"})


def locations(request):
    qs = Location.objects.filter(is_active=True)
    return render(request, "hotel/locations.html", {
        "domestic": qs.filter(is_international=False),
        "international": qs.filter(is_international=True),
        "nav": "locations",
    })


def static_page(template, nav):
    def view(request):
        return render(request, f"hotel/{template}.html", {"nav": nav})
    view.__name__ = template
    return view


about = static_page("about", "about")
dining = static_page("dining", "dining")
amenities = static_page("amenities", "amenities")
gallery = static_page("gallery", "gallery")


def contact(request):
    form = ContactForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        msg = form.save()
        from django.core.mail import send_mail
        try:
            send_mail(
                f"New enquiry from {msg.name}",
                f"From: {msg.name} <{msg.email}>\n\n{msg.message}",
                settings.DEFAULT_FROM_EMAIL,
                [settings.HOTEL_CONTACT_EMAIL],
            )
        except Exception:
            logger.exception("Contact email failed")
        messages.success(request, "Thank you for contacting us! We'll get back to you shortly.")
        return redirect("contact")
    return render(request, "hotel/contact.html", {"form": form, "nav": "contact"})


# ---------------------------------------------------------------------- auth
def signup(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, f"Welcome to MKR Hotels, {user.first_name or user.username}!")
        return redirect(request.GET.get("next") or "booking")
    return render(request, "registration/signup.html", {"form": form})


# ------------------------------------------------------------------- booking
@require_GET
def check_availability(request):
    """JSON endpoint used by the booking form to show live price + availability."""
    form = AvailabilityForm(request.GET)
    if not form.is_valid():
        return JsonResponse({"ok": False, "errors": {k: v[0] for k, v in form.errors.items()}})
    d = form.cleaned_data
    nights = (d["check_out"] - d["check_in"]).days
    count = services.availability_count(d["location"], d["room_type"], d["check_in"], d["check_out"])
    return JsonResponse({
        "ok": True,
        "available": count,
        "nights": nights,
        "rate": d["room_type"].price_per_night,
        "total": d["room_type"].price_per_night * nights,
    })


@login_required
def booking(request):
    services.expire_stale_bookings()
    if request.method == "POST":
        form = BookingForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            try:
                new_booking = services.create_booking(
                    user=request.user,
                    location=d["location"],
                    room_type=d["room_type"],
                    check_in=d["check_in"],
                    check_out=d["check_out"],
                    guest_name=d["guest_name"],
                    guest_email=d["guest_email"],
                    guest_phone=d["guest_phone"],
                    guests=d["guests"],
                    special_requests=d["special_requests"],
                )
            except services.NoRoomAvailable:
                form.add_error(None, f"Sorry, no {d['room_type'].name} is free in {d['location'].name} for those dates. Try other dates or another room type.")
            else:
                return redirect("payment", reference=new_booking.reference)
    else:
        initial = {
            "guest_name": request.user.get_full_name() or request.user.username,
            "guest_email": request.user.email,
        }
        for field in ("room_type", "location"):
            slug = request.GET.get(field)
            model = RoomType if field == "room_type" else Location
            if slug:
                initial[field] = model.objects.filter(slug=slug).first()
        form = BookingForm(initial=initial)
    prices = {rt.pk: rt.price_per_night for rt in RoomType.objects.all()}
    return render(request, "hotel/booking.html", {
        "form": form,
        "prices_json": json.dumps(prices),
        "today": timezone.localdate().isoformat(),
        "nav": "booking",
    })


def _own_booking(request, reference):
    booking = get_object_or_404(Booking.objects.select_related("room__location", "room__room_type"), reference=reference)
    if booking.user_id != request.user.id and not request.user.is_staff:
        raise Http404
    return booking


@login_required
def payment(request, reference):
    booking = _own_booking(request, reference)
    if booking.status == Booking.Status.CONFIRMED:
        return redirect(booking)
    if booking.status != Booking.Status.PENDING or booking.hold_expired:
        if booking.status == Booking.Status.PENDING:
            booking.status = Booking.Status.EXPIRED
            booking.save(update_fields=["status"])
        messages.error(request, "This booking is no longer awaiting payment. Please book again.")
        return redirect("booking")
    try:
        order = services.create_payment_order(booking)
    except Exception:
        logger.exception("Could not create payment order")
        messages.error(request, "We couldn't reach the payment gateway. Please try again in a minute.")
        return redirect("my_bookings")
    return render(request, "hotel/payment.html", {
        "booking": booking,
        "order": order,
        "amount_paise": booking.total_amount * 100,
        "razorpay_key": settings.RAZORPAY_KEY_ID,
        "demo_mode": order.provider == "demo",
        "nav": "booking",
    })


@login_required
@require_POST
def payment_verify(request, reference):
    """Razorpay Checkout posts here after a successful payment."""
    booking = _own_booking(request, reference)
    order_id = request.POST.get("razorpay_order_id", "")
    payment_id = request.POST.get("razorpay_payment_id", "")
    signature = request.POST.get("razorpay_signature", "")
    order = booking.payments.filter(order_id=order_id, provider="razorpay").first()
    if not order or not services.verify_razorpay_signature(order_id, payment_id, signature):
        logger.warning("Payment signature check failed for %s", booking.reference)
        messages.error(request, "We couldn't verify that payment. If money was deducted, it will be refunded automatically by Razorpay; please contact us with your booking reference.")
        return redirect("payment", reference=booking.reference)
    booking = services.mark_paid(order, payment_id, signature)
    return _after_payment(request, booking)


@login_required
@require_POST
def payment_demo(request, reference):
    """Simulated payment, only available in local development without Razorpay keys."""
    if not settings.PAYMENT_DEMO_MODE:
        raise Http404
    booking = _own_booking(request, reference)
    order = get_object_or_404(booking.payments, order_id=request.POST.get("order_id", ""), provider="demo")
    booking = services.mark_paid(order, "demo_pay_" + order.order_id[-8:])
    return _after_payment(request, booking)


def _after_payment(request, booking):
    if booking.status == Booking.Status.CONFIRMED:
        messages.success(request, f"Payment received. Booking {booking.reference} is confirmed! A confirmation email is on its way.")
    else:
        messages.error(request, "Sorry, the room was taken while you were paying. Your payment has been refunded.")
    return redirect(booking)


@login_required
@require_POST
def payment_failed(request, reference):
    booking = _own_booking(request, reference)
    order = booking.payments.filter(order_id=request.POST.get("order_id", ""), status=Payment.Status.CREATED).first()
    if order:
        order.status = Payment.Status.FAILED
        order.save(update_fields=["status"])
    messages.error(request, request.POST.get("reason") or "Payment failed. You can try again.")
    return redirect("payment", reference=booking.reference)


@csrf_exempt
@require_POST
def razorpay_webhook(request):
    """Backup confirmation in case the customer closes the tab right after paying.
    Configure in Razorpay Dashboard → Webhooks with the 'payment.captured' event."""
    if not services.verify_webhook_signature(request.body, request.headers.get("X-Razorpay-Signature")):
        return HttpResponseBadRequest("bad signature")
    try:
        event = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest("bad json")
    if event.get("event") in ("payment.captured", "order.paid"):
        entity = event["payload"]["payment"]["entity"]
        order = Payment.objects.filter(order_id=entity.get("order_id")).first()
        if order:
            services.mark_paid(order, entity.get("id", ""))
    return HttpResponse("ok")


@login_required
def booking_receipt(request, reference):
    booking = _own_booking(request, reference)
    if booking.status == Booking.Status.PENDING:
        return redirect("payment", reference=booking.reference)
    return render(request, "hotel/receipt.html", {
        "booking": booking,
        "payment": booking.payments.exclude(status=Payment.Status.CREATED).exclude(status=Payment.Status.FAILED).first(),
    })


@login_required
def my_bookings(request):
    services.expire_stale_bookings()
    bookings = request.user.bookings.select_related("room__location", "room__room_type")
    return render(request, "hotel/my_bookings.html", {"bookings": bookings, "nav": "my_bookings"})


@login_required
@require_POST
def cancel(request, reference):
    booking = _own_booking(request, reference)
    booking, refunded = services.cancel_booking(booking)
    if booking.status == Booking.Status.CANCELLED:
        msg = f"Booking {booking.reference} cancelled."
        if refunded:
            msg += " Your refund has been started and usually reaches you in 5–7 working days."
        messages.success(request, msg)
    else:
        messages.error(request, "This booking can no longer be cancelled online. Please contact us.")
    return redirect("my_bookings")
