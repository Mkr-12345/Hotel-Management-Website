from django.conf import settings


def site_info(request):
    return {
        "HOTEL_PHONE": "+91 9306008959",
        "HOTEL_EMAIL": settings.HOTEL_CONTACT_EMAIL,
        "HOTEL_ADDRESS": "MKR Hotels HQ, Sonipat, Haryana",
        "PAYMENT_DEMO_MODE": settings.PAYMENT_DEMO_MODE,
    }
