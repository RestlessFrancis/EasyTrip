from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('trip/<int:trip_id>/', views.trip_detail, name='trip_detail'),
    path('trip/<int:trip_id>/delete/', views.delete_trip, name='delete_trip'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('logout/', views.logout_view, name='logout'),
]
