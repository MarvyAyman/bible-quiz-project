from django.db import migrations


def backfill(apps, schema_editor):
    Category = apps.get_model('quiz', 'Category')
    Material = apps.get_model('quiz', 'Material')
    Badge    = apps.get_model('quiz', 'Badge')

    # 1. Create default categories (idempotent)
    defaults = [
        ('bible',     'كتاب مقدس',       '📖'),
        ('spiritual', 'كتاب روحي',       '📚'),
        ('iqraa',     'اقرأ واعرف واكسب', '📁'),
    ]
    key_to_obj = {}
    for i, (key, name, icon) in enumerate(defaults, start=1):
        obj, _ = Category.objects.get_or_create(
            key=key,
            defaults={
                'name': name,
                'icon': icon,
                'has_links': True,
                'link_mode': 'multiple',
                'order': i,
                'is_active': True,
            },
        )
        key_to_obj[key] = obj

    # 2. Assign every existing Material to `bible` by default
    #    (the original CharField values were dropped by migration 0009)
    default_category = key_to_obj['bible']
    for mat in Material.objects.all():
        mat.category_new_id = default_category.id
        mat.save(update_fields=['category_new'])

    # 3. Badge.category_filter_new stays NULL → "applies to all categories"
    #    No action needed; nullable field is fine as-is.


def reverse_backfill(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('quiz', '0009_add_category_safely'),
    ]
    operations = [
        migrations.RunPython(backfill, reverse_backfill),
    ]