from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db import IntegrityError
from .models import Trip, ItineraryDay
import datetime
import random
import requests
import urllib.parse

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
        except Exception as e:
            print(f"Error fetching Wikipedia summary for {destination}: {e}")

        # 2. Fetch coordinates from Nominatim API using the corrected search_query
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

        # 3. Fetch background image using the corrected search_query
        clean_img_query = urllib.parse.quote(search_query)
        image_url = f"https://loremflickr.com/1200/400/{clean_img_query},city/all"

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
    
    context = {
        'trip': trip,
        'days': days
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
