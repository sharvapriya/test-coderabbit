from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .forms import SignUpForm, sanitize_username
from .models import Profile


class UsernameSanitizationTests(TestCase):
    def test_sanitize_username_keeps_supported_characters(self):
        self.assertEqual(sanitize_username("  John Doe+Dev  "), "john_doedev")
        self.assertEqual(sanitize_username("Jane.Doe@example.com"), "jane.doe")

    def test_signup_form_normalizes_username_and_email(self):
        form = SignUpForm(
            data={
                "username": " John Doe ",
                "email": "John@Example.COM",
                "phone_number": "9876543210",
                "password1": "SafePassword123",
                "password2": "SafePassword123",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["username"], "john_doe")
        self.assertEqual(form.cleaned_data["email"], "john@example.com")


class UsernameSuggestionApiTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user_model.objects.create_user(username="admin", email="taken@example.com", password="x")

    def test_username_availability_reports_taken_and_available(self):
        taken_response = self.client.get(
            reverse("accounts:username_availability"),
            {"username": "Admin"},
        )
        available_response = self.client.get(
            reverse("accounts:username_availability"),
            {"username": "Jane.Doe"},
        )

        self.assertEqual(taken_response.status_code, 200)
        self.assertJSONEqual(
            taken_response.content,
            {"username": "admin", "available": False, "message": "Already taken"},
        )

        self.assertEqual(available_response.status_code, 200)
        self.assertJSONEqual(
            available_response.content,
            {"username": "jane.doe", "available": True, "message": "Available"},
        )

    def test_username_suggestions_return_available_options_from_typed_username(self):
        response = self.client.get(
            reverse("accounts:username_suggestions"),
            {"username": "admin"},
        )

        self.assertEqual(response.status_code, 200)
        suggestions = response.json()["suggestions"]
        self.assertGreaterEqual(len(suggestions), 3)
        self.assertLessEqual(len(suggestions), 5)
        self.assertNotIn("admin", suggestions)
        self.assertEqual(len(suggestions), len(set(suggestions)))
        for suggestion in suggestions:
            self.assertTrue(suggestion.startswith("admin"))
            self.assertFalse(self.user_model.objects.filter(username__iexact=suggestion).exists())

    def test_username_suggestions_are_empty_without_typed_username(self):
        response = self.client.get(reverse("accounts:username_suggestions"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["suggestions"], [])


class SignupFlowTests(TestCase):
    @patch("accounts.forms.send_welcome_email")
    def test_signup_creates_sanitized_unique_username_and_profile(self, _send_welcome_email):
        response = self.client.post(
            reverse("accounts:signup"),
            data={
                "username": " Jane Doe ",
                "email": "Jane@Example.com",
                "phone_number": "9999999999",
                "password1": "AnotherSafePass123",
                "password2": "AnotherSafePass123",
            },
        )

        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(email="jane@example.com")
        profile = Profile.objects.get(user=user)
        self.assertEqual(user.username, "jane_doe")
        self.assertEqual(user.first_name, "")
        self.assertEqual(user.last_name, "")
        self.assertEqual(profile.phone_number, "9999999999")

    @patch("accounts.forms.send_welcome_email")
    def test_signup_rejects_taken_username_case_insensitively(self, _send_welcome_email):
        get_user_model().objects.create_user(username="jane_doe", email="existing@example.com", password="x")

        response = self.client.post(
            reverse("accounts:signup"),
            data={
                "username": "Jane_Doe",
                "email": "new@example.com",
                "phone_number": "9999999999",
                "password1": "AnotherSafePass123",
                "password2": "AnotherSafePass123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This username is already taken.")
