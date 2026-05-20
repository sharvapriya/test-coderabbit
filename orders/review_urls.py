from django.urls import path

from . import views


app_name = "reviews"


urlpatterns = [
    path("add/", views.review_add, name="add"),
    path("product/<int:product_id>/", views.product_reviews, name="product_reviews"),
    path("report/<int:review_id>/", views.report_review, name="report"),
]
