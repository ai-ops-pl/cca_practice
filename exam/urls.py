from django.urls import path

from . import views

urlpatterns = [
    path("", views.start, name="start"),
    path("begin/", views.begin, name="begin"),
    path("attempt/<uuid:attempt_id>/", views.take, name="take"),
    path("attempt/<uuid:attempt_id>/autosave/", views.autosave, name="autosave"),
    path("attempt/<uuid:attempt_id>/pause/", views.pause_toggle, name="pause"),
    path("attempt/<uuid:attempt_id>/submit/", views.submit, name="submit"),
    path("attempt/<uuid:attempt_id>/results/", views.results, name="results"),
    path("attempt/<uuid:attempt_id>/review/", views.review, name="review"),
    path("attempt/<uuid:attempt_id>/delete/", views.delete_attempt, name="delete_attempt"),
    path("results/delete-all/", views.delete_all_results, name="delete_all_results"),
    path("results/delete-selected/", views.delete_selected_attempts, name="delete_selected_attempts"),
]
