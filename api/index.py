import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bible_quiz_project.settings')

from django.core.wsgi import get_wsgi_application
app = get_wsgi_application()
