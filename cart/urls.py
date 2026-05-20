from django.urls import path
from .views import buy_now, cart_add, cart_detail, cart_remove, cart_update_quantity


app_name = "cart"
urlpatterns = [
    path('add/<int:product_id>/', cart_add, name="cart_add"),
    path('buy-now/<int:product_id>/', buy_now, name="buy_now"),
    path("",cart_detail, name="cart_detail"),
    path("remove/<int:product_id>/", cart_remove, name="remove_item"),
    path("update/<int:item_id>/<str:action>/", cart_update_quantity, name="update_quantity"),
]

