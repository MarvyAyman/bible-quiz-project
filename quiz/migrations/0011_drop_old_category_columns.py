from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('quiz', '0010_backfill_category_fks'),
    ]
    operations = [
        migrations.RunSQL(
            sql=[
                "ALTER TABLE quiz_material DROP COLUMN IF EXISTS category;",
                "ALTER TABLE quiz_badge DROP COLUMN IF EXISTS category_filter;",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]