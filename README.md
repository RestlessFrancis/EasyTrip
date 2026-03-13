# Easytrip: Travel Itinerary Planner

Easytrip is a Django-based web application that helps users quickly generate and manage personalized travel itineraries based on their destination, dates, group size, and interests. It integrates with Wikipedia, OpenStreetMap, and Overpass API to fetch real destination data and points of interest.

---

## Features

### Trip Planning
- **Create trips** – Submit a form with destination, trip length (days), group size, start/end dates, and interests
- **Auto-generated itineraries** – Each trip gets day-by-day itinerary placeholders based on trip length
- **Interest-based customization** – Choose from 12 interest categories: Nature, Food, History, Beaches, Nightlife, Shopping, Photography, Architecture, Adventure, Art, Wellness, Markets

### Trip Detail Page
- **Overview** – Wikipedia-sourced summary and highlights for the destination
- **Interactive map** – Leaflet map showing the destination with coordinates
- **Recommended places** – Real points of interest from OpenStreetMap, grouped by your interests (e.g., restaurants, parks, museums)
- **Tabbed navigation** – Overview and Recommended Places tabs

### User Dashboard
- **View all trips** – List of your saved trips, ordered by creation date
- **Recent trips grid** – On the home page for logged-in users
- **Delete trips** – Remove trips from your dashboard

### Authentication
- **Sign up** – Create account (username, email, password)
- **Log in** – Username and password
- **Log out** – End session
- **Optional login** – Unauthenticated users can generate trips; authenticated users can save and access them in a dashboard

### Admin
- **Django admin** – Manage users and data at `/admin/` (requires superuser)

### API
- **Spots by category** – `GET /api/spots/?destination=Cebu City&category=Nature` returns real POIs from OpenStreetMap for a destination and interest category

---

## Functions & Routes

| Route | Function | Description |
|-------|----------|-------------|
| `/` | `home` | Landing page with trip form; shows recent trips for logged-in users |
| `/dashboard/` | `dashboard` | User’s saved trips |
| `/trip/<id>/` | `trip_detail` | Full trip view: overview, itinerary days, map, recommended spots |
| `/trip/<id>/delete/` | `delete_trip` | Delete a trip (redirects to dashboard) |
| `/login/` | `login_view` | Login form |
| `/signup/` | `signup_view` | Registration form |
| `/logout/` | `logout_view` | Logout (redirects to login) |
| `/api/spots/` | `spots_by_category` | API: spots for destination + category |
| `/admin/` | Django admin | Admin panel |

---

## Data Models

### Trip
- `user` (ForeignKey, optional)
- `destination`, `trip_length`, `group_size`
- `start_date`, `end_date`
- `interests` (JSONField)
- `title`, `overview`, `image_url`
- `latitude`, `longitude`
- `created_at`

### ItineraryDay
- `trip` (ForeignKey)
- `day_number`
- `description`

---

## External Services

| Service | Purpose |
|---------|---------|
| **Wikipedia REST API** | Destination overview, spell-corrected titles, coordinates, images |
| **Nominatim (OpenStreetMap)** | Geocoding for lat/lon and bounding boxes |
| **Overpass API** | Real points of interest (restaurants, parks, museums, etc.) by category |
| **Unsplash** | Fallback destination image when Wikipedia has none |

---

## Interest Categories (Overpass filters)

- **Nature** – Parks, nature reserves, peaks, waterfalls  
- **Food** – Restaurants, cafes, fast food  
- **History** – Historic sites, museums  
- **Beaches** – Beaches, marinas  
- **Nightlife** – Bars, nightclubs, pubs  
- **Shopping** – Malls, department stores  
- **Photography** – Viewpoints, attractions  
- **Architecture** – Buildings, historic structures  
- **Adventure** – Climbing, sports centres, surfing, diving  
- **Art** – Museums, galleries, arts centres  
- **Wellness** – Spas, fitness centres  
- **Markets** – Marketplaces, market shops  

---

## Project Structure

```
├── easytrip/           # Django project settings, URLs, WSGI/ASGI
├── planner/            # Main app: models, views, urls
├── templates/          # home.html, dashboard.html, detail.html, login.html, signup.html, base.html
├── static/             # CSS, images
├── manage.py
├── requirements.txt
└── db.sqlite3          # SQLite database (local dev)
```

---

## Setup

1. **Clone and enter project**
   ```bash
   cd jamesdjango
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   .\venv\Scripts\Activate.ps1   # Windows
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run migrations**
   ```bash
   python manage.py migrate
   ```

5. **Create superuser (optional)**
   ```bash
   python manage.py createsuperuser
   ```

6. **Run server**
   ```bash
   python manage.py runserver
   ```

7. Open **http://127.0.0.1:8000/**

---

## Database

- **Local**: SQLite (`db.sqlite3`) – no extra setup
- **Production**: Set `DATABASE_URL` for PostgreSQL (e.g. `postgres://user:pass@host:5432/dbname`); add `psycopg2-binary` to `requirements.txt` for production deploys

---

## Tech Stack

- Django 6.0
- Python 3
- SQLite (default) / PostgreSQL (via `dj-database-url`)
- Whitenoise (static files)
- Pillow (image handling)
- Leaflet (maps)
- Wikipedia, Nominatim, Overpass APIs
