"""
SAFE DATA MIGRATION — copies old Quiz data into new Material shape.
Does NOT delete the old Quiz table or any old data — that happens
later in 0006, only after this has been verified to work correctly.
"""
from django.db import migrations


def copy_quiz_data_to_material(apps, schema_editor):
    Quiz = apps.get_model('quiz', 'Quiz')
    Material = apps.get_model('quiz', 'Material')
    Question = apps.get_model('quiz', 'Question')
    Score = apps.get_model('quiz', 'Score')

    quiz_to_material_map = {}

    for quiz in Quiz.objects.all():
        material = Material.objects.create(
            category='bible',  # all existing old data is Bible-category by definition
            source_name=quiz.book_name,
            chapter_number=quiz.chapter_number,
            title=quiz.title or '',
            slug=quiz.slug,
            is_active=quiz.is_active,
            created_at=quiz.created_at,
        )
        quiz_to_material_map[quiz.id] = material.id

    for quiz_id, material_id in quiz_to_material_map.items():
        Question.objects.filter(quiz_id=quiz_id).update(material_id=material_id)
        Score.objects.filter(quiz_id=quiz_id).update(material_id=material_id)


def reverse_copy(apps, schema_editor):
    Material = apps.get_model('quiz', 'Material')
    Material.objects.filter(category='bible').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('quiz', '0004_materiallink_questionchoice_and_more'),
    ]

    operations = [
        migrations.RunPython(copy_quiz_data_to_material, reverse_copy),
    ]