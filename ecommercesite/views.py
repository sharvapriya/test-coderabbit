from django.shortcuts import render


def contact_page(request):
    return render(request, "site/contact.html")


def privacy_policy_page(request):
    return render(request, "site/privacy_policy.html")


def terms_conditions_page(request):
    return render(request, "site/terms_conditions.html")


def refund_cancellation_policy_page(request):
    return render(request, "site/refund_cancellation_policy.html")


def shipping_delivery_policy_page(request):
    return render(request, "site/shipping_delivery_policy.html")
