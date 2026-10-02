from django.contrib import admin

from .models import Attempt, Question


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("bank", "number", "domain", "qtype", "scenario", "correct")
    list_filter = ("bank", "domain", "qtype", "scenario")
    search_fields = ("text",)


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ("id", "bank", "candidate", "started_at", "submitted_at", "scaled_score", "passed")
    list_filter = ("bank", "passed", "auto_submitted")
