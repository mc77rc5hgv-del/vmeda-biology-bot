"""Shared launch policy. Public entry never bypasses subject entitlements."""
import os


def public_launch():
    return os.environ.get('MINIAPP_ACCESS_MODE', 'admin_only').strip().lower() == 'public'
