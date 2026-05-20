from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-vw$4kjb@u+@o#ic7k+=_$__x0c#%d*u@jzk2kz1b$ind+&6-b3'

DEBUG = True


ALLOWED_HOSTS = [
    'mykartstore.com',
    'www.mykartstore.com',
    'localhost',
    '127.0.0.1'
    
]



INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'products',
    'cart',
    'orders',
    'wishlist',
    'accounts',
    'sellers.apps.SellersConfig',
   
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'ecommercesite.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'ecommercesite.context_processors.site_context',
                'wishlist.context_processors.wishlist_count',
                'orders.context_processors.wallet_context',
            ],
            'libraries': {
                'admin_dashboard': 'products.templatetags.admin_dashboard',
            },
        },
    },
]

WSGI_APPLICATION = 'ecommercesite.wsgi.application'


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'en'

LANGUAGES = [
    ('en', 'English'),
    ('ta', 'Tamil'),
    ('hi', 'Hindi'),
    ('te', 'Telugu'),
    ('ml', 'Malayalam'),
]

LOCALE_PATHS = [
    BASE_DIR / 'locale',
]

TIME_ZONE = 'Asia/Kolkata'

USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'mediafiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "products:home"
LOGOUT_REDIRECT_URL = "products:home"

SELLER_PLATFORM_COMMISSION_RATE = "10.00"
SELLER_PAYMENT_GATEWAY_FEE_RATE = "2.00"
SELLER_GST_RATE = "18.00"
SELLER_TDS_RATE = "1.00"
SELLER_PAYOUT_ADDITIONAL_HOLD_DAYS = 7
SELLER_RETURN_WINDOW_DAYS = 7
SELLER_DEFAULT_DELIVERY_CHARGE = "50.00"
SELLER_RETURN_EXTRA_DELIVERY_CHARGE = "50.00"
SELLER_RAZORPAY_PAYOUT_MODE = "mock"


# Email — Gmail SMTP via SSL (port 465)
# 1. Tell Django to use the SMTP server (remove the console backend if you added it earlier)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

# 2. Your cPanel SMTP server address
EMAIL_HOST = 'mail.mykartstore.com'

# 3. Account/auth email address
EMAIL_HOST_USER = 'no-reply@mykartstore.com'

# 4. The password you just created for this email account in cPanel
EMAIL_HOST_PASSWORD = 'Mykart@123' 

# 5. Security and Port settings (cPanel standard for SSL is 465)
EMAIL_PORT = 465 
EMAIL_USE_SSL = True
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

# Application email identities
ACCOUNT_NOTIFICATIONS_EMAIL = 'no-reply@mykartstore.com'
CUSTOMER_NOTIFICATIONS_EMAIL = 'notifications@mykartstore.com'
SELLER_NOTIFICATIONS_EMAIL = 'business@mykartstore.com'
SUPPORT_EMAIL = 'support@mykartstore.com'
DEFAULT_REPLY_TO_EMAIL = [SUPPORT_EMAIL]

SITE_BUSINESS_NAME = "MyKartStore"
SITE_SUPPORT_EMAIL = SUPPORT_EMAIL
SITE_SUPPORT_PHONE = "+91 99654 08000"
SITE_ADDRESS_LINES = (
    "MyKartStore",
    "Coimbatore, Tamil Nadu 641012",
    "India",
)
SITE_SERVICE_REGIONS = "Across India"
SITE_SHIPPING_PROCESSING_TIME = "Orders are usually processed within 1-2 business days."
SITE_SHIPPING_TIMELINE = "Delivery usually takes 3-7 business days depending on the destination."
SITE_SHIPPING_CHARGES = "Shipping charges are included in the product price. Free shipping on orders above ₹500."
SITE_REFUND_TIMELINE = "Approved refunds are processed within 5-7 business days to the wallet"
SITE_RETURN_WINDOW_DAYS = 7

RAZORPAY_KEY_ID = "rzp_test_ShFvzc2Fxj9wT6"
RAZORPAY_KEY_SECRET = "l57t29rWfq00CMVf7ytu6e3K"
RAZORPAY_CURRENCY = "INR"
RAZORPAY_REQUEST_TIMEOUT_SECONDS = 10

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "[%(asctime)s] %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "loggers": {
        "orders.payment": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}



DEBUG = True

if DEBUG:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False


else:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
