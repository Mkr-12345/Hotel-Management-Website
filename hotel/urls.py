from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("rooms/", views.rooms, name="rooms"),
    path("rooms/<slug:slug>/", views.room_detail, name="room_detail"),
    path("dining/", views.dining, name="dining"),
    path("amenities/", views.amenities, name="amenities"),
    path("gallery/", views.gallery, name="gallery"),
    path("locations/", views.locations, name="locations"),
    path("contact/", views.contact, name="contact"),
    path("signup/", views.signup, name="signup"),
    path("booking/", views.booking, name="booking"),
    path("booking/availability/", views.check_availability, name="check_availability"),
    path("booking/<str:reference>/pay/", views.payment, name="payment"),
    path("booking/<str:reference>/pay/verify/", views.payment_verify, name="payment_verify"),
    path("booking/<str:reference>/pay/demo/", views.payment_demo, name="payment_demo"),
    path("booking/<str:reference>/pay/failed/", views.payment_failed, name="payment_failed"),
    path("booking/<str:reference>/receipt/", views.booking_receipt, name="booking_receipt"),
    path("booking/<str:reference>/cancel/", views.cancel, name="cancel_booking"),
    path("my-bookings/", views.my_bookings, name="my_bookings"),
    path("payments/razorpay/webhook/", views.razorpay_webhook, name="razorpay_webhook"),
]
