from django.contrib import admin

from .models import Attempt, Question


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("number", "domain", "qtype", "scenario", "correct")
    list_filter = ("domain", "qtype", "scenario")
    search_fields = ("text",)


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ("id", "candidate", "started_at", "submitted_at", "scaled_score", "passed")
    list_filter = ("passed", "auto_submitted")
