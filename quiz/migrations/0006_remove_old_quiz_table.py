"""
FINAL CLEANUP — only run this after manually verifying that every old
Quiz row has a matching Material row with the same data (Step 7 in
our checklist: Quiz.objects.count() == Material.objects.filter(
category='bible').count() must be True).
This is destructive (drops the Quiz table) and should be the very
last step, with your CSV backups already saved beforehand.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('quiz', '0005_copy_quiz_to_material'),
    ]

    operations = [
        migrations.RemoveField(model_name='question', name='quiz'),
        migrations.RemoveField(model_name='score', name='quiz'),

        migrations.AlterField(
            model_name='question',
            name='material',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='questions', to='quiz.material'),
        ),
        migrations.AlterField(
            model_name='score',
            name='material',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='scores', to='quiz.material'),
        ),

        migrations.DeleteModel(name='Quiz'),
    ]