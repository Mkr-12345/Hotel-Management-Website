from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "MKR Hotels Admin"
admin.site.site_title = "MKR Hotels Admin"
admin.site.index_title = "Manage rooms, bookings and payments"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("hotel.urls")),
]
