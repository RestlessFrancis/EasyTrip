from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User

class Trip(models.fields.Field):
    pass

class Trip(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    destination = models.CharField(max_length=200)
    trip_length = models.IntegerField(default=3)
    group_size = models.CharField(max_length=50, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    interests = models.JSONField(default=list, blank=True)
    
    # Generated content
    title = models.CharField(max_length=200, blank=True)
    overview = models.TextField(blank=True)
    image_url = models.URLField(max_length=500, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.title or self.destination

class ItineraryDay(models.Model):
    trip = models.ForeignKey(Trip, related_name='days', on_delete=models.CASCADE)
    day_number = models.IntegerField()
    description = models.TextField()

    class Meta:
        ordering = ['day_number']

    def __str__(self):
        return f"Day {self.day_number} - {self.trip.destination}"
