from django.db import DatabaseError

from .models import Category


def sidebar_categories(request):
    """
    Makes `all_sidebar_categories` available in every template
    (used by base_panel.html for the "➕ إضافة مادة جديدة" shortcuts).
    """
    try:
        categories = list(
            Category.objects.filter(is_active=True).order_by('order', 'id')
        )
    except DatabaseError:
        # e.g. before migrations have been run
        categories = []
    return {'all_sidebar_categories': categories}