from decimal import Decimal
from .models import Wallet


# def wallet_context(request):
#     """Add user's wallet to template context"""
#     wallet_balance = Decimal("0")
#     wallet_obj = None
def wallet_context(request):
    """Add user's wallet to template context"""
    if request.path.startswith("/admin/"):
        return {
            "user_wallet_balance": Decimal("0"),
            "user_wallet": None,
        }

    wallet_balance = Decimal("0")
    wallet_obj = None


    if request.user.is_authenticated:
        try:
            wallet_obj = request.user.wallet
            wallet_balance = wallet_obj.balance
        except Wallet.DoesNotExist:
            wallet_balance = Decimal("0")

    return {
        "user_wallet_balance": wallet_balance,
        "user_wallet": wallet_obj,
    }
