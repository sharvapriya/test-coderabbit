from django.urls import path
from . import views


# app_name= 'products'

# urlpatterns = [
#     path('', views.home, name='home'),  # homepage

#     path('shop/', views.product_list, name='product_list'),

#     path('category/<slug:category_slug>/', 
#          views.product_list, 
#          name='product_list_by_category'),

#     path('product/<int:id>/<slug:slug>/', 
#          views.product_detail, 
#          name="product_detail"),
# ]
app_name = "products"

urlpatterns = [
    path("", views.home, name="home"),
    path("categories/", views.category_directory, name="category_directory"),
    path("shop/", views.product_list, name="product_list"),
    path("shop/checkout-add/", views.checkout_add_selected_products, name="checkout_add_selected_products"),
    path("stock-alert/<int:product_id>/", views.subscribe_stock_alert, name="subscribe_stock_alert"),
    path("<slug:category_slug>/", views.product_list, name="product_list_by_category"),
    path("<int:id>/<slug:slug>/", views.product_detail, name="product_detail"),
]
