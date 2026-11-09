import hashlib
import hmac
import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import Booking, Location, Payment, Room, RoomType


class BaseCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_hotel", verbosity=0)
        cls.user = User.objects.create_user("manish", "m@example.com", "Str0ng-pass!", first_name="Manish")
        cls.goa = Location.objects.get(slug="goa")
        cls.deluxe = RoomType.objects.get(slug="deluxe-suite")
        cls.presidential = RoomType.objects.get(slug="presidential-suite")

    def setUp(self):
        self.client.force_login(self.user)
        self.ci = timezone.localdate() + timedelta(days=10)
        self.co = self.ci + timedelta(days=3)

    def booking_data(self, room_type=None, **extra):
        data = {
            "guest_name": "Manish", "guest_email": "m@example.com", "guest_phone": "+91 9306008959",
            "location": self.goa.pk, "room_type": (room_type or self.deluxe).pk,
            "check_in": self.ci.isoformat(), "check_out": self.co.isoformat(), "guests": 2,
        }
        data.update(extra)
        return data


class PageTests(BaseCase):
    def test_public_pages_render(self):
        self.client.logout()
        for name in ["home", "about", "rooms", "dining", "amenities", "gallery", "locations", "contact", "login", "signup"]:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertContains(self.client.get(reverse("room_detail", args=["deluxe-suite"])), "Deluxe Suite")

    def test_booking_requires_login(self):
        self.client.logout()
        r = self.client.get(reverse("booking"))
        self.assertRedirects(r, reverse("login") + "?next=" + reverse("booking"))

    def test_contact_form_saves_and_emails(self):
        r = self.client.post(reverse("contact"), {"name": "A", "email": "a@b.com", "message": "Hi"}, follow=True)
        self.assertContains(r, "Thank you")
        self.assertEqual(len(mail.outbox), 1)

    def test_signup(self):
        self.client.logout()
        r = self.client.post(reverse("signup"), {
            "username": "newguest", "first_name": "New Guest", "email": "new@example.com",
            "password1": "Very-secret-123", "password2": "Very-secret-123",
        })
        self.assertRedirects(r, reverse("booking"))
        self.assertTrue(User.objects.filter(username="newguest", email="new@example.com").exists())


@override_settings(PAYMENT_DEMO_MODE=True)
class DemoFlowTests(BaseCase):
    def test_full_booking_flow(self):
        r = self.client.post(reverse("booking"), self.booking_data())
        booking = Booking.objects.get()
        self.assertRedirects(r, reverse("payment", args=[booking.reference]))
        self.assertEqual(booking.total_amount, 8000 * 3)
        self.assertEqual(booking.status, Booking.Status.PENDING)

        page = self.client.get(reverse("payment", args=[booking.reference]))
        self.assertContains(page, "demo")
        order = booking.payments.get()

        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(reverse("payment_demo", args=[booking.reference]), {"order_id": order.order_id})
        self.assertRedirects(r, reverse("booking_receipt", args=[booking.reference]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(booking.reference, mail.outbox[0].subject)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("cancel_booking", args=[booking.reference]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(booking.payments.get().status, Payment.Status.REFUNDED)

    def test_no_double_booking(self):
        # Goa has exactly one Presidential Suite.
        self.client.post(reverse("booking"), self.booking_data(self.presidential))
        r = self.client.post(reverse("booking"), self.booking_data(self.presidential))
        self.assertContains(r, "no Presidential Suite is free")
        self.assertEqual(Booking.objects.count(), 1)
        # Non-overlapping dates are fine (check-out day = next check-in day).
        r = self.client.post(reverse("booking"), self.booking_data(
            self.presidential, check_in=self.co.isoformat(), check_out=(self.co + timedelta(days=1)).isoformat()))
        self.assertEqual(Booking.objects.count(), 2)

    def test_expired_hold_releases_room(self):
        self.client.post(reverse("booking"), self.booking_data(self.presidential))
        Booking.objects.update(created_at=timezone.now() - timedelta(minutes=60))
        r = self.client.post(reverse("booking"), self.booking_data(self.presidential))
        self.assertEqual(Booking.objects.filter(status=Booking.Status.PENDING).count(), 1)
        self.assertEqual(Booking.objects.filter(status=Booking.Status.EXPIRED).count(), 1)

    def test_validation(self):
        past = (timezone.localdate() - timedelta(days=1)).isoformat()
        r = self.client.post(reverse("booking"), self.booking_data(check_in=past))
        self.assertContains(r, "can&#x27;t be in the past")
        r = self.client.post(reverse("booking"), self.booking_data(check_out=self.ci.isoformat()))
        self.assertContains(r, "Check-out must be after check-in")
        r = self.client.post(reverse("booking"), self.booking_data(guests=6))
        self.assertContains(r, "fits up to 2 guests")
        self.assertFalse(Booking.objects.exists())

    def test_availability_endpoint(self):
        r = self.client.get(reverse("check_availability"), {
            "location": self.goa.pk, "room_type": self.deluxe.pk,
            "check_in": self.ci.isoformat(), "check_out": self.co.isoformat(), "guests": 2,
        })
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["available"], 4)
        self.assertEqual(data["total"], 24000)

    def test_other_users_cannot_see_booking(self):
        self.client.post(reverse("booking"), self.booking_data())
        booking = Booking.objects.get()
        other = User.objects.create_user("x", "x@example.com", "Str0ng-pass!")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("payment", args=[booking.reference])).status_code, 404)
        self.assertEqual(self.client.get(reverse("booking_receipt", args=[booking.reference])).status_code, 404)


@override_settings(PAYMENT_DEMO_MODE=False, RAZORPAY_KEY_ID="rzp_test_abc", RAZORPAY_KEY_SECRET="secret123",
                   RAZORPAY_WEBHOOK_SECRET="whsec")
class RazorpayTests(BaseCase):
    def make_booking(self):
        fake_client = mock.Mock()
        fake_client.order.create.return_value = {"id": "order_TEST123"}
        with mock.patch.object(services, "razorpay_client", return_value=fake_client):
            self.client.post(reverse("booking"), self.booking_data())
            booking = Booking.objects.get()
            page = self.client.get(reverse("payment", args=[booking.reference]))
        self.assertContains(page, "checkout.razorpay.com")
        self.assertContains(page, "order_TEST123")
        fake_client.order.create.assert_called_once()
        self.assertEqual(fake_client.order.create.call_args[0][0]["amount"], 24000 * 100)
        return booking

    @staticmethod
    def sign(text, secret="secret123"):
        return hmac.new(secret.encode(), text.encode(), hashlib.sha256).hexdigest()

    def test_valid_signature_confirms(self):
        booking = self.make_booking()
        r = self.client.post(reverse("payment_verify", args=[booking.reference]), {
            "razorpay_order_id": "order_TEST123", "razorpay_payment_id": "pay_1",
            "razorpay_signature": self.sign("order_TEST123|pay_1"),
        })
        self.assertRedirects(r, reverse("booking_receipt", args=[booking.reference]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)

    def test_bad_signature_rejected(self):
        booking = self.make_booking()
        self.client.post(reverse("payment_verify", args=[booking.reference]), {
            "razorpay_order_id": "order_TEST123", "razorpay_payment_id": "pay_1", "razorpay_signature": "forged",
        })
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.PENDING)

    def test_demo_endpoint_disabled_with_real_keys(self):
        booking = self.make_booking()
        r = self.client.post(reverse("payment_demo", args=[booking.reference]), {"order_id": "order_TEST123"})
        self.assertEqual(r.status_code, 404)

    def test_webhook_confirms(self):
        booking = self.make_booking()
        body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_9", "order_id": "order_TEST123"}}}})
        r = self.client.post(reverse("razorpay_webhook"), body, content_type="application/json",
                             HTTP_X_RAZORPAY_SIGNATURE=self.sign(body, "whsec"))
        self.assertEqual(r.status_code, 200)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        r = self.client.post(reverse("razorpay_webhook"), body, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE="bad")
        self.assertEqual(r.status_code, 400)

    def test_cancel_refunds_through_razorpay(self):
        booking = self.make_booking()
        services.mark_paid(booking.payments.get(), "pay_1")
        fake_client = mock.Mock()
        fake_client.payment.refund.return_value = {"id": "rfnd_1"}
        with mock.patch.object(services, "razorpay_client", return_value=fake_client):
            self.client.post(reverse("cancel_booking", args=[booking.reference]))
        fake_client.payment.refund.assert_called_once_with("pay_1", {"amount": 2400000})
        self.assertEqual(booking.payments.get().refund_id, "rfnd_1")

    def test_late_payment_after_room_taken_is_refunded(self):
        booking = self.make_booking()
        Booking.objects.filter(pk=booking.pk).update(created_at=timezone.now() - timedelta(hours=1))
        # Every other Deluxe Suite in Goa gets booked meanwhile, including this one's room.
        for room in Room.objects.filter(location=self.goa, room_type=self.deluxe):
            Booking.objects.create(user=self.user, room=room, guest_name="X", guest_email="x@x.com", guest_phone="1234567",
                                   check_in=self.ci, check_out=self.co, nightly_rate=1, total_amount=1,
                                   status=Booking.Status.CONFIRMED)
        fake_client = mock.Mock()
        fake_client.payment.refund.return_value = {"id": "rfnd_late"}
        with mock.patch.object(services, "razorpay_client", return_value=fake_client):
            result = services.mark_paid(booking.payments.get(), "pay_late")
        self.assertEqual(result.status, Booking.Status.CANCELLED)
        fake_client.payment.refund.assert_called_once()
