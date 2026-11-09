# MKR Hotels – Hotel Booking Website (Django)

A fully functional hotel booking website built with **Django**, intergated 
HTML/CSS/JS version (kept for reference in `original-html/`).

## Features
- **9 hotel locations** (India + international) and **5 room types**, all managed from the database
- **User accounts** – sign up, login, logout, password reset
- **Real bookings** – date-based availability check, no double booking, live price calculation
- **Online payments with Razorpay** – UPI, cards, net banking, wallets; server-side signature verification and webhook backup
- **Room hold** – an unpaid booking holds the room for 15 minutes, then releases it
- **My Bookings** – booking history, printable receipts, cancellation with automatic Razorpay refund
- **Email notifications** – booking confirmation and cancellation emails, contact-form enquiries
- **Admin dashboard** – manage locations, rooms, prices, bookings, payments and messages
- Responsive layout, keyboard and screen-reader friendly (labels, skip link, focus styles)

## Tech stack
Python · Django 5 · SQLite · Razorpay · HTML · CSS · JavaScript

## Run locally
```bash
python -m venv venv
venv\Scripts\activate            # Windows   (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # macOS/Linux: cp .env.example .env
python manage.py migrate
python manage.py seed_hotel      # loads locations, room types and 118 rooms
python manage.py createsuperuser # your admin login
python manage.py runserver
```
Open http://127.0.0.1:8000 for the site and http://127.0.0.1:8000/admin for the admin panel.

Without Razorpay keys the site runs in **demo payment mode** (a button simulates payment),
so you can test the whole flow immediately.

## Turn on real Razorpay payments
1. Create an account at https://dashboard.razorpay.com and switch to **Test Mode**.
2. Account & Settings → API Keys → Generate Test Key.
3. Put the key ID and secret in `.env` as `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`, and restart the server.
4. Pay with Razorpay's test UPI/cards (see Razorpay docs → Test Card Details).
5. Going live: complete Razorpay KYC, generate **Live** keys, set `DJANGO_DEBUG=False`.
6. Optional but recommended once deployed: add a webhook to
   `https://<your-domain>/payments/razorpay/webhook/` with the `payment.captured` event and put its secret in `RAZORPAY_WEBHOOK_SECRET`.

## Tests
```bash
python manage.py test hotel
```
16 tests cover the pages, signup, the booking flow, double-booking prevention, room holds,
Razorpay signature/webhook verification, refunds and access control.

## Project structure
```
mkrhotels/           project settings and URLs
hotel/models.py      Location, RoomType, Room, Booking, Payment, ContactMessage
hotel/services.py    availability, booking creation, payments, refunds, emails
hotel/views.py       pages, booking, payment, receipt, my bookings
hotel/templates/     HTML templates (same design as the original site)
hotel/static/        shared stylesheet
original-html/       the original static website
```
