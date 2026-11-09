"""Load the locations, room types and rooms from the original MKR Hotels site.

    python manage.py seed_hotel

Safe to run more than once: existing records are updated, not duplicated.
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from hotel.models import Location, Room, RoomType

LOCATIONS = [
    # name, country, international, description, image
    ("Delhi", "India", False, "Experience culture, history, and luxury in India's vibrant capital city.",
     "https://images.pexels.com/photos/1796706/pexels-photo-1796706.jpeg?auto=compress&cs=tinysrgb&w=1200"),
    ("Mumbai", "India", False, "Stay in the heart of India's entertainment and financial capital.",
     "https://images.pexels.com/photos/3584437/pexels-photo-3584437.jpeg?auto=compress&cs=tinysrgb&w=1200"),
    ("Jaipur", "India", False, "Enjoy regal experiences in the Pink City with royal hospitality.",
     "https://images.pexels.com/photos/674010/pexels-photo-674010.jpeg?auto=compress&cs=tinysrgb&w=1200"),
    ("Goa", "India", False, "Unwind in our beachside resorts with tropical vibes and lively nightlife.",
     "https://images.pexels.com/photos/460672/pexels-photo-460672.jpeg?auto=compress&cs=tinysrgb&w=1200"),
    ("Bangalore", "India", False, "Modern business suites and comfort in India's tech capital.",
     "https://images.pexels.com/photos/17083659/pexels-photo-17083659.jpeg?auto=compress&cs=tinysrgb&w=1200"),
    ("Paris", "France", True, "Romance and elegance near the Eiffel Tower and Champs-Élysées.",
     "https://images.pexels.com/photos/338515/pexels-photo-338515.jpeg?auto=compress&cs=tinysrgb&w=1200"),
    ("New York", "USA", True, "Stay in the heart of Manhattan with skyline views and Broadway nearby.",
     "https://images.pexels.com/photos/378570/pexels-photo-378570.jpeg?auto=compress&cs=tinysrgb&w=1200"),
    ("Dubai", "UAE", True, "Luxury and innovation meet in our five-star towers near Burj Khalifa.",
     "https://images.pexels.com/photos/17865557/pexels-photo-17865557.jpeg?auto=compress&cs=tinysrgb&w=1200"),
    ("Tokyo", "Japan", True, "Urban serenity with cutting-edge comfort and cultural immersion.",
     "https://images.pexels.com/photos/30435802/pexels-photo-30435802.jpeg?auto=compress&cs=tinysrgb&w=1200"),
]

ROOM_TYPES = [
    # name, price, max guests, features, description, image
    ("Deluxe Suite", 8000, 2, "King-size bed, Smart lighting, Minibar, City view",
     "Luxurious suite with king-sized bed, smart lighting, minibar, and city views. Ideal for travelers seeking elegance and comfort.",
     "https://images.pexels.com/photos/261395/pexels-photo-261395.jpeg?auto=compress&cs=tinysrgb&w=1200"),
    ("Executive Room", 6000, 2, "High-speed Wi-Fi, Ergonomic workspace, Premium amenities",
     "Contemporary interior, high-speed Wi-Fi, ergonomic workspace, and premium amenities for business travelers.",
     "https://images.pexels.com/photos/271624/pexels-photo-271624.jpeg?auto=compress&cs=tinysrgb&w=1200"),
    ("Family Room", 5000, 5, "Multiple beds, Kid-friendly services, Spacious layout",
     "Designed for families, includes multiple beds, kid-friendly services, and a cozy, spacious atmosphere.",
     "https://images.pexels.com/photos/262048/pexels-photo-262048.jpeg?auto=compress&cs=tinysrgb&w=1200"),
    ("Ocean View Room", 9500, 3, "Panoramic sea view, Balcony seating, Large windows",
     "Wake up to panoramic views of the ocean, with large windows, balcony seating, and calming interiors.",
     "https://images.pexels.com/photos/258154/pexels-photo-258154.jpeg?auto=compress&cs=tinysrgb&w=1200"),
    ("Presidential Suite", 25000, 4, "Private lounge, Butler service, Jacuzzi",
     "The epitome of luxury: private lounge, butler service, jacuzzi, and exquisite design for an unforgettable stay.",
     "https://images.pexels.com/photos/261187/pexels-photo-261187.jpeg?auto=compress&cs=tinysrgb&w=1200"),
]

# How many physical rooms of each type every hotel gets.
ROOMS_PER_HOTEL = {"Deluxe Suite": 4, "Executive Room": 4, "Family Room": 3, "Presidential Suite": 1}
OCEAN_VIEW_HOTELS = {"Mumbai": 3, "Goa": 4, "Dubai": 3}


class Command(BaseCommand):
    help = "Create/update MKR Hotels locations, room types and rooms."

    def handle(self, *args, **options):
        locations = {}
        for name, country, intl, desc, img in LOCATIONS:
            locations[name], _ = Location.objects.update_or_create(
                slug=slugify(name),
                defaults=dict(name=name, country=country, is_international=intl, description=desc, image_url=img),
            )
        types = {}
        for order, (name, price, guests, feats, desc, img) in enumerate(ROOM_TYPES):
            types[name], _ = RoomType.objects.update_or_create(
                slug=slugify(name),
                defaults=dict(name=name, price_per_night=price, max_guests=guests, features=feats,
                              description=desc, image_url=img, sort_order=order),
            )
        created = 0
        for loc_name, loc in locations.items():
            plan = dict(ROOMS_PER_HOTEL)
            if loc_name in OCEAN_VIEW_HOTELS:
                plan["Ocean View Room"] = OCEAN_VIEW_HOTELS[loc_name]
            floor = 1
            for type_name, count in plan.items():
                for i in range(1, count + 1):
                    _, was_created = Room.objects.get_or_create(
                        location=loc, number=f"{floor}{i:02d}", defaults={"room_type": types[type_name]}
                    )
                    created += was_created
                floor += 1
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(locations)} locations, {len(types)} room types, {created} new rooms."
        ))
