from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.http import JsonResponse
from .models import Trip, ItineraryDay
import datetime
import random
import requests
import urllib.parse

# Maps interest category names to Overpass API query filters
CATEGORY_OVERPASS_FILTERS = {
    'Nature': [
        'node["leisure"="nature_reserve"]',
        'node["natural"="peak"]',
        'node["natural"="waterfall"]',
        'node["leisure"="park"]',
        'way["leisure"="nature_reserve"]',
    ],
    'Food': [
        'node["amenity"="restaurant"]',
        'node["amenity"="cafe"]',
        'node["amenity"="fast_food"]',
        'node["amenity"="food_court"]',
    ],
    'History': [
        'node["historic"]',
        'node["tourism"="museum"]',
        'way["historic"]',
    ],
    'Beaches': [
        'node["natural"="beach"]',
        'way["natural"="beach"]',
        'node["leisure"="marina"]',
    ],
    'Nightlife': [
        'node["amenity"="bar"]',
        'node["amenity"="nightclub"]',
        'node["amenity"="pub"]',
    ],
    'Shopping': [
        'node["shop"="mall"]',
        'node["shop"="department_store"]',
        'node["shop"="supermarket"]',
        'way["shop"="mall"]',
    ],
    'Photography': [
        'node["tourism"="viewpoint"]',
        'node["tourism"="attraction"]',
    ],
    'Architecture': [
        'node["tourism"="attraction"]',
        'way["historic"="building"]',
        'node["historic"="building"]',
    ],
    'Adventure': [
        'node["sport"="climbing"]',
        'node["leisure"="sports_centre"]',
        'node["sport"="surfing"]',
        'node["sport"="diving"]',
    ],
    'Art': [
        'node["tourism"="museum"]',
        'node["tourism"="gallery"]',
        'node["amenity"="arts_centre"]',
    ],
    'Wellness': [
        'node["leisure"="spa"]',
        'node["amenity"="spa"]',
        'node["leisure"="fitness_centre"]',
    ],
    'Markets': [
        'node["amenity"="marketplace"]',
        'node["shop"="market"]',
        'way["amenity"="marketplace"]',
    ],
}

def spots_by_category(request):
    """
    GET /api/spots/?destination=Cebu City&category=Nature
    Returns a list of real POI spots from OpenStreetMap via Overpass API.
    """
    destination = request.GET.get('destination', '').strip()
    category = request.GET.get('category', '').strip()

    if not destination or not category:
        return JsonResponse({'error': 'Missing destination or category'}, status=400)

    filters = CATEGORY_OVERPASS_FILTERS.get(category, [])
    if not filters:
        return JsonResponse({'spots': []})

    headers = {'User-Agent': 'EasytripApp/1.0'}

    # Step 1: Geocode destination to get bounding box
    try:
        geocode_url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(destination)}&format=json&limit=1"
        geo_resp = requests.get(geocode_url, headers=headers, timeout=6)
        geo_data = geo_resp.json()
        if not geo_data:
            return JsonResponse({'spots': [], 'message': 'Destination not found'})
        place = geo_data[0]
        bbox = place.get('boundingbox')  # [south, north, west, east]
        if not bbox:
            lat = float(place['lat'])
            lon = float(place['lon'])
            delta = 0.15
            bbox = [lat - delta, lat + delta, lon - delta, lon + delta]
        south, north, west, east = bbox[0], bbox[1], bbox[2], bbox[3]
        bbox_str = f"{south},{west},{north},{east}"
    except Exception as e:
        return JsonResponse({'error': f'Geocoding failed: {str(e)}'}, status=500)

    # Step 2: Build and run Overpass query
    try:
        union_parts = '\n'.join([f'  {f}({bbox_str});' for f in filters])
        overpass_query = f"""
[out:json][timeout:15];
(
{union_parts}
);
out body 30;
"""
        overpass_url = "https://overpass-api.de/api/interpreter"
        ov_resp = requests.post(overpass_url, data={'data': overpass_query}, headers=headers, timeout=18)
        ov_data = ov_resp.json()
        elements = ov_data.get('elements', [])
    except Exception as e:
        return JsonResponse({'error': f'Overpass query failed: {str(e)}'}, status=500)

    # Step 3: Parse results into clean spot list
    spots = []
    seen_names = set()
    for el in elements:
        tags = el.get('tags', {})
        name = tags.get('name') or tags.get('name:en') or tags.get('name:fil')
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        spot_type = (
            tags.get('amenity') or tags.get('leisure') or
            tags.get('tourism') or tags.get('natural') or
            tags.get('historic') or tags.get('shop') or
            tags.get('sport') or 'place'
        ).replace('_', ' ').title()

        spots.append({
            'name': name,
            'type': spot_type,
            'lat': el.get('lat'),
            'lon': el.get('lon'),
        })
        if len(spots) >= 20:
            break

    return JsonResponse({'spots': spots, 'category': category, 'destination': destination})


def home(request):
    if request.method == 'POST':
        destination = request.POST.get('destination')
        trip_length = request.POST.get('trip_length', 3)
        group_size = request.POST.get('group_size', '')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        interests = request.POST.getlist('interests')

        # Convert dates if present
        def parse_date(date_str):
            if date_str:
                try:
                    return datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    return None
            return None

        s_date = parse_date(start_date)
        e_date = parse_date(end_date)

        # Setup defaults
        lat = 0.0
        lon = 0.0
        image_url = ''
        search_query = destination

        # 1. Fetch overview from Wikipedia API (also gives us spell-corrected titles and fallback coordinates)
        overview_text = f"Get ready for an amazing adventure in {destination}. This itinerary is tailored to your interests: {', '.join(interests) if interests else 'everything'}."
        try:
            clean_destination = urllib.parse.quote(destination)
            wiki_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{clean_destination}"
            headers = {'User-Agent': 'EasytripApp/1.0'}
            wiki_response = requests.get(wiki_url, headers=headers, timeout=5)
            if wiki_response.status_code == 200:
                wiki_data = wiki_response.json()
                if 'extract' in wiki_data:
                    overview_text = wiki_data['extract']
                if 'title' in wiki_data:
                    search_query = wiki_data['title']
                if 'coordinates' in wiki_data:
                    lat = wiki_data['coordinates']['lat']
                    lon = wiki_data['coordinates']['lon']
                # Extract image from Wikipedia response
                if 'originalimage' in wiki_data:
                    image_url = wiki_data['originalimage']['source']
                elif 'thumbnail' in wiki_data:
                    image_url = wiki_data['thumbnail']['source']
        except Exception as e:
            print(f"Error fetching Wikipedia summary for {destination}: {e}")

        # Fallback image if Wikipedia had none
        if not image_url:
            image_url = f"https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?auto=format&fit=crop&q=80&w=1200"

        try:
            headers = {'User-Agent': 'EasytripApp/1.0'}
            geocode_url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(search_query)}&format=json&limit=1"
            response = requests.get(geocode_url, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data:
                    lat = float(data[0]['lat'])
                    lon = float(data[0]['lon'])
        except Exception as e:
            print(f"Error geocoding {search_query}: {e}")


        trip = Trip.objects.create(
            user=request.user if request.user.is_authenticated else None,
            destination=search_query,
            trip_length=trip_length,
            group_size=group_size,
            start_date=s_date,
            end_date=e_date,
            interests=interests,
            title=f"{trip_length} days in {destination}",
            overview=overview_text,
            image_url=image_url,
            latitude=lat,
            longitude=lon
        )
        
        # Create dummy itinerary days
        for i in range(1, int(trip_length) + 1):
             ItineraryDay.objects.create(
                 trip=trip,
                 day_number=i,
                 description=f"Day {i} in {destination}. Explore the top sights and enjoy local cuisine."
             )

        return redirect('trip_detail', trip_id=trip.id)

    # Get recent trips for the grid
    if request.user.is_authenticated:
        recent_trips = Trip.objects.filter(user=request.user).order_by('-created_at')[:4]
    else:
        recent_trips = Trip.objects.none()
    
    context = {
        'recent_trips': recent_trips
    }
    return render(request, 'home.html', context)

def trip_detail(request, trip_id):
    trip = get_object_or_404(Trip, id=trip_id)
    days = trip.days.all()

    # Fetch recommended spots for each interest category
    recommended_spots = []
    if trip.interests and trip.destination:
        headers = {'User-Agent': 'EasytripApp/1.0'}
        try:
            geocode_url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(trip.destination)}&format=json&limit=1"
            geo_resp = requests.get(geocode_url, headers=headers, timeout=6)
            geo_data = geo_resp.json()
            if geo_data:
                place = geo_data[0]
                bbox = place.get('boundingbox')
                if bbox:
                    south, north, west, east = bbox[0], bbox[1], bbox[2], bbox[3]
                else:
                    lat = float(place['lat']); lon = float(place['lon']); d = 0.15
                    south, north, west, east = lat-d, lat+d, lon-d, lon+d
                bbox_str = f"{south},{west},{north},{east}"

                seen_names = set()
                for category in trip.interests[:5]:
                    filters = CATEGORY_OVERPASS_FILTERS.get(category, [])
                    if not filters:
                        continue
                    union_parts = '\n'.join([f'  {f}({bbox_str});' for f in filters])
                    overpass_query = f"[out:json][timeout:12];\n(\n{union_parts}\n);\nout body 15;\n"
                    try:
                        ov_resp = requests.post(
                            "https://overpass-api.de/api/interpreter",
                            data={'data': overpass_query}, headers=headers, timeout=14
                        )
                        elements = ov_resp.json().get('elements', [])
                        cat_spots = []
                        for el in elements:
                            tags = el.get('tags', {})
                            name = tags.get('name') or tags.get('name:en') or tags.get('name:fil')
                            if not name or name in seen_names:
                                continue
                            seen_names.add(name)
                            spot_type = (
                                tags.get('amenity') or tags.get('leisure') or
                                tags.get('tourism') or tags.get('natural') or
                                tags.get('historic') or tags.get('shop') or
                                tags.get('sport') or 'place'
                            ).replace('_', ' ').title()
                            cat_spots.append({
                                'name': name, 'type': spot_type,
                                'lat': el.get('lat'), 'lon': el.get('lon'),
                                'category': category,
                            })
                            if len(cat_spots) >= 6:
                                break
                        if cat_spots:
                            recommended_spots.append({'category': category, 'spots': cat_spots})
                    except Exception:
                        continue
        except Exception:
            pass

    context = {
        'trip': trip,
        'days': days,
        'recommended_spots': recommended_spots,
    }
    return render(request, 'detail.html', context)


def dashboard(request):
    if request.user.is_authenticated:
        trips = Trip.objects.filter(user=request.user).order_by('-created_at')
    else:
        trips = Trip.objects.none()
    
    context = {
        'trips': trips
    }
    return render(request, 'dashboard.html', context)

def delete_trip(request, trip_id):
    # Allow GET for simpler frontend integration bypassing form submission issues
    trip = get_object_or_404(Trip, id=trip_id)
    if trip.user == request.user or trip.user is None:
        trip.delete()
    return redirect('dashboard')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        username = request.POST.get('username', '')
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.GET.get('next', 'home')
            return redirect(next_url)
        else:
            return render(request, 'login.html', {
                'error': 'Invalid username or password. Please try again.',
                'username': username,
            })
    return render(request, 'login.html')


def logout_view(request):
    logout(request)
    return redirect('login')


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        username = request.POST.get('username', '')
        email = request.POST.get('email', '')
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        
        if password != confirm_password:
            return render(request, 'signup.html', {
                'error': 'Passwords do not match.',
                'username': username,
                'email': email,
            })
            
        try:
            user = User.objects.create_user(username=username, email=email, password=password)
            login(request, user)  # Log the user in immediately after signup
            return redirect('home')
        except IntegrityError:
            return render(request, 'signup.html', {
                'error': 'Username is already taken. Please choose another.',
                'username': username,
                'email': email,
            })
            
    return render(request, 'signup.html')
