from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.http import JsonResponse
from django.conf import settings
from django.core.mail import send_mail
from django.core.cache import cache
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from .models import Trip, ItineraryDay, LoginToken
import datetime
import json
import random
from decimal import Decimal, InvalidOperation
import requests
import urllib.parse
from groq import Groq

# ---- Login attempt constants ----
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 300  # 5 minutes


# ---- Email helper ----
def send_email(subject, to_email, html_content):
    """Send email using Resend in production or Gmail SMTP locally."""
    resend_key = getattr(settings, 'RESEND_API_KEY', '')
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'Easytrip <onboarding@resend.dev>')

    if resend_key:
        try:
            import resend
            resend.api_key = resend_key
            resend.Emails.send({
                "from": from_email,
                "to": [to_email],
                "subject": subject,
                "html": html_content,
            })
            print(f"[EMAIL] Sent via Resend to {to_email}")
        except Exception as e:
            print(f"[EMAIL ERROR] Resend failed: {e}")
    else:
        try:
            plain = strip_tags(html_content)
            send_mail(
                subject=subject,
                message=plain,
                from_email=from_email,
                recipient_list=[to_email],
                html_message=html_content,
                fail_silently=False,
            )
            print(f"[EMAIL] Sent via Gmail SMTP to {to_email}")
        except Exception as e:
            print(f"[EMAIL ERROR] Gmail SMTP failed: {e}")


# ---- Spot rating helper ----
def _spot_rating(name):
    h = sum(ord(c) for c in (name or '')) % 100
    return round(3.5 + (h / 100) * 1.5, 1)


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
    destination = request.GET.get('destination', '').strip()
    category = request.GET.get('category', '').strip()

    if not destination or not category:
        return JsonResponse({'error': 'Missing destination or category'}, status=400)

    filters = CATEGORY_OVERPASS_FILTERS.get(category, [])
    if not filters:
        return JsonResponse({'spots': []})

    headers = {'User-Agent': 'EasytripApp/1.0'}

    try:
        geocode_url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(destination)}&format=json&limit=1"
        geo_resp = requests.get(geocode_url, headers=headers, timeout=6)
        geo_data = geo_resp.json()
        if not geo_data:
            return JsonResponse({'spots': [], 'message': 'Destination not found'})
        place = geo_data[0]
        bbox = place.get('boundingbox')
        if not bbox:
            lat = float(place['lat'])
            lon = float(place['lon'])
            delta = 0.15
            bbox = [lat - delta, lat + delta, lon - delta, lon + delta]
        south, north, west, east = bbox[0], bbox[1], bbox[2], bbox[3]
        bbox_str = f"{south},{west},{north},{east}"
    except Exception as e:
        return JsonResponse({'error': f'Geocoding failed: {str(e)}'}, status=500)

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
            'rating': _spot_rating(name),
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
        budget_total = request.POST.get('budget_total', '').strip()
        budget_currency = request.POST.get('budget_currency', 'USD').strip()

        def parse_date(date_str):
            if date_str:
                try:
                    return datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    return None
            return None

        s_date = parse_date(start_date)
        e_date = parse_date(end_date)

        lat = 0.0
        lon = 0.0
        image_url = ''
        search_query = destination

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
                if 'originalimage' in wiki_data:
                    image_url = wiki_data['originalimage']['source']
                elif 'thumbnail' in wiki_data:
                    image_url = wiki_data['thumbnail']['source']
        except Exception as e:
            print(f"Error fetching Wikipedia summary for {destination}: {e}")

        if not image_url or any(kw in image_url.lower() for kw in ['map', 'flag', 'coat', 'locator', 'blank', 'svg']):
            image_url = f"https://source.unsplash.com/800x600/?{urllib.parse.quote(destination)},travel,landscape"

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

        bt = None
        if budget_total:
            try:
                bt = Decimal(budget_total)
            except (ValueError, TypeError, InvalidOperation):
                pass
        budget_breakdown = {}
        for key in ('accommodation', 'food', 'activities', 'transport'):
            val = request.POST.get(f'budget_{key}', '').strip()
            if val:
                try:
                    budget_breakdown[key] = float(val)
                except (ValueError, TypeError):
                    pass

        trip = Trip.objects.create(
            user=request.user if request.user.is_authenticated else None,
            destination=search_query,
            trip_length=trip_length,
            group_size=group_size,
            start_date=s_date,
            end_date=e_date,
            interests=interests,
            budget_total=bt,
            budget_currency=budget_currency or 'USD',
            budget_breakdown=budget_breakdown,
            title=f"{trip_length} days in {destination}",
            overview=overview_text,
            image_url=image_url,
            latitude=lat,
            longitude=lon
        )

        # Send confirmation email
        if request.user.is_authenticated and request.user.email:
            try:
                html_message = render_to_string('emails/trip_created.html', {
                    'user': request.user,
                    'trip': trip,
                    'site_url': settings.SITE_URL,
                })
                send_email(
                    subject=f'✈️ Your Easytrip itinerary for {trip.destination} is ready!',
                    to_email=request.user.email,
                    html_content=html_message,
                )
            except Exception as e:
                print(f"[EMAIL ERROR] {e}")

        return redirect('trip_detail', trip_id=trip.id)

    if request.user.is_authenticated:
        recent_trips = Trip.objects.filter(user=request.user).order_by('-created_at')[:4]
    else:
        recent_trips = Trip.objects.none()

    context = {'recent_trips': recent_trips}
    return render(request, 'home.html', context)


def trip_detail(request, trip_id):
    trip = get_object_or_404(Trip, id=trip_id)
    days = trip.days.all()

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
                                'rating': _spot_rating(name),
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

    breakdown_total = 0
    budget_exceeded = False
    if trip.budget_total and trip.budget_breakdown:
        breakdown_total = sum(
            float(v) for k, v in trip.budget_breakdown.items()
            if isinstance(v, (int, float))
        )
        budget_exceeded = breakdown_total > float(trip.budget_total)

    parsed_days = []
    for day in days:
        try:
            parsed_days.append(json.loads(day.description))
        except (json.JSONDecodeError, TypeError):
            parsed_days.append(None)

    context = {
        'trip': trip,
        'days': days,
        'parsed_days': parsed_days,
        'has_generated': any(d is not None for d in parsed_days),
        'recommended_spots': recommended_spots,
        'budget_exceeded': budget_exceeded,
        'breakdown_total': breakdown_total,
        'mapbox_token': settings.MAPBOX_TOKEN,
    }
    return render(request, 'detail.html', context)


def generate_itinerary(request, trip_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    trip = get_object_or_404(Trip, id=trip_id)

    interests_str = ', '.join(trip.interests) if trip.interests else 'general sightseeing'
    budget_str = f"{trip.budget_currency} {trip.budget_total}" if trip.budget_total else 'unspecified'
    group_str = trip.group_size if trip.group_size else 'a small group'

    prompt = f"""You are an expert travel planner. Generate a detailed {trip.trip_length}-day itinerary for a trip to {trip.destination}.

Trip details:
- Group: {group_str}
- Interests: {interests_str}
- Total Budget: {budget_str}
- Dates: {trip.start_date} to {trip.end_date}

Return ONLY a valid JSON array (no markdown, no explanation) with exactly {trip.trip_length} objects, one per day:
[
  {{
    "day": 1,
    "theme": "Short catchy theme for the day",
    "morning": {{
      "activity": "Activity name",
      "description": "2-3 sentence description with practical details.",
      "duration": "e.g. 2-3 hours",
      "cost": "e.g. Free / $10 per person"
    }},
    "afternoon": {{
      "activity": "Activity name",
      "description": "2-3 sentence description.",
      "duration": "e.g. 3 hours",
      "cost": "e.g. $15 per person"
    }},
    "evening": {{
      "activity": "Activity name",
      "description": "2-3 sentence description.",
      "duration": "e.g. 2 hours",
      "cost": "e.g. $20-30 per person"
    }},
    "estimated_daily_cost": "e.g. $50-80 per person",
    "local_tip": "One practical insider tip for this day."
  }}
]"""

    try:
        client = Groq(api_key=settings.GROQ_API_KEY)
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.7,
        )
        raw_text = completion.choices[0].message.content.strip()

        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        raw_text = raw_text.strip()

        days_data = json.loads(raw_text)

        trip.days.all().delete()
        for day in days_data:
            ItineraryDay.objects.create(
                trip=trip,
                day_number=day['day'],
                description=json.dumps(day)
            )

        return JsonResponse({'success': True, 'days': days_data})

    except json.JSONDecodeError as e:
        return JsonResponse({'error': f'Failed to parse AI response: {str(e)}'}, status=500)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def monitor_dashboard(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return redirect('login')

    from django.db.models import Count, Max
    total_users = User.objects.count()
    total_trips = Trip.objects.count()
    today = timezone.now().date()
    trips_today = Trip.objects.filter(created_at__date=today).count()
    trips_this_week = Trip.objects.filter(
        created_at__date__gte=today - datetime.timedelta(days=7)
    ).count()

    users = User.objects.annotate(
        trip_count=Count('trip'),
        last_trip=Max('trip__created_at')
    ).order_by('-date_joined')

    search_q = request.GET.get('q', '').strip()
    trips = Trip.objects.select_related('user').order_by('-created_at')
    if search_q:
        trips = trips.filter(destination__icontains=search_q) | \
                Trip.objects.filter(user__username__icontains=search_q).order_by('-created_at')

    popular_destinations = (
        Trip.objects.values('destination')
        .annotate(count=Count('destination'))
        .order_by('-count')[:10]
    )

    context = {
        'total_users': total_users,
        'total_trips': total_trips,
        'trips_today': trips_today,
        'trips_this_week': trips_this_week,
        'users': users,
        'trips': trips[:50],
        'popular_destinations': popular_destinations,
        'search_q': search_q,
    }
    return render(request, 'monitor.html', context)


def monitor_user_detail(request, user_id):
    if not request.user.is_authenticated or not request.user.is_staff:
        return redirect('login')
    profile_user = get_object_or_404(User, id=user_id)
    trips = Trip.objects.filter(user=profile_user).order_by('-created_at')
    context = {
        'profile_user': profile_user,
        'trips': trips,
        'trip_count': trips.count(),
    }
    return render(request, 'monitor_user.html', context)


def dashboard(request):
    if request.user.is_authenticated:
        trips = Trip.objects.filter(user=request.user).order_by('-created_at')
    else:
        trips = Trip.objects.none()
    return render(request, 'dashboard.html', {'trips': trips})


def delete_trip(request, trip_id):
    trip = get_object_or_404(Trip, id=trip_id)
    if trip.user == request.user or trip.user is None:
        trip.delete()
    return redirect('dashboard')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        lock_key = f'login_lock_{username}'
        attempt_key = f'login_attempts_{username}'
        locked_until = cache.get(lock_key)

        if locked_until:
            remaining = int((locked_until - timezone.now()).total_seconds())
            return render(request, 'login.html', {
                'error': 'Too many failed attempts.',
                'locked': True,
                'remaining': max(remaining, 0),
                'username': username,
            })

        user = authenticate(request, username=username, password=password)

        if user is not None:
            cache.delete(attempt_key)
            cache.delete(lock_key)
            login(request, user)
            return redirect(request.GET.get('next', 'home'))
        else:
            attempts = cache.get(attempt_key, 0) + 1
            cache.set(attempt_key, attempts, LOCKOUT_SECONDS * 2)
            remaining_attempts = MAX_ATTEMPTS - attempts

            if attempts >= MAX_ATTEMPTS:
                locked_until = timezone.now() + datetime.timedelta(seconds=LOCKOUT_SECONDS)
                cache.set(lock_key, locked_until, LOCKOUT_SECONDS)
                cache.delete(attempt_key)
                return render(request, 'login.html', {
                    'error': 'Too many failed attempts.',
                    'locked': True,
                    'remaining': LOCKOUT_SECONDS,
                    'username': username,
                })

            return render(request, 'login.html', {
                'error': f'Invalid username or password. {remaining_attempts} attempt{"s" if remaining_attempts != 1 else ""} remaining.',
                'attempts_left': remaining_attempts,
                'username': username,
            })

    return render(request, 'login.html')


def send_magic_link(request):
    if request.method != 'POST':
        return redirect('login')

    username = request.POST.get('username', '').strip()

    user = None
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        try:
            user = User.objects.get(email=username)
        except User.DoesNotExist:
            pass

    if user and user.email:
        LoginToken.objects.filter(user=user, used=False).update(used=True)
        token = LoginToken.objects.create(user=user)
        magic_url = f"{settings.SITE_URL}/magic-link/verify/{token.token}/"

        try:
            html_message = render_to_string('emails/magic_link.html', {
                'user': user,
                'magic_url': magic_url,
                'site_url': settings.SITE_URL,
            })
            send_email(
                subject='🔐 Your Easytrip login link',
                to_email=user.email,
                html_content=html_message,
            )
        except Exception as e:
            print(f"[MAGIC LINK ERROR] {e}")

    return render(request, 'login.html', {
        'magic_sent': True,
        'username': username,
    })


def verify_magic_link(request, token):
    try:
        login_token = LoginToken.objects.get(token=token)
    except LoginToken.DoesNotExist:
        return render(request, 'login.html', {
            'error': 'This login link is invalid or has already been used.'
        })

    if not login_token.is_valid():
        return render(request, 'login.html', {
            'error': 'This login link has expired. Please request a new one.'
        })

    login_token.used = True
    login_token.save()

    user = login_token.user
    user.backend = 'django.contrib.auth.backends.ModelBackend'
    login(request, user)

    return redirect('home')


def logout_view(request):
    logout(request)
    return redirect('login')


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        username = request.POST.get('username', '')
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not email:
            return render(request, 'signup.html', {
                'error': 'Email address is required to receive trip notifications.',
                'username': username,
            })

        if password != confirm_password:
            return render(request, 'signup.html', {
                'error': 'Passwords do not match.',
                'username': username,
                'email': email,
            })
        try:
            user = User.objects.create_user(username=username, email=email, password=password)
            login(request, user)
            return redirect('home')
        except IntegrityError:
            return render(request, 'signup.html', {
                'error': 'Username is already taken. Please choose another.',
                'username': username,
                'email': email,
            })
    return render(request, 'signup.html')