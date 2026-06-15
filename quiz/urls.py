from django.urls import path, re_path
from . import views

urlpatterns = [
    path('', views.index_view, name='index'),
    re_path(r'^quiz/(?P<quiz_slug>[\w\u0600-\u06FF%-]+)/$', views.quiz_view, name='quiz_view'),
    re_path(r'^quiz/(?P<quiz_slug>[\w\u0600-\u06FF%-]+)/submit/$', views.submit_score, name='submit_score'),
    re_path(r'^quiz/(?P<quiz_slug>[\w\u0600-\u06FF%-]+)/leaderboard/$', views.leaderboard_view, name='leaderboard_view'),

    # Panel (staff-only)
    path('panel/', views.panel_dashboard, name='panel_dashboard'),
    path('panel/quizzes/', views.manage_quizzes, name='manage_quizzes'),
    re_path(r'^panel/quiz/(?P<quiz_slug>[\w\u0600-\u06FF%-]+)/edit/$', views.edit_existing_quiz, name='edit_existing_quiz'),
    re_path(r'^panel/quiz/(?P<quiz_slug>[\w\u0600-\u06FF%-]+)/delete/$', views.delete_quiz, name='delete_quiz'),
    path('panel/quiz/new/', views.create_quiz_step1, name='create_quiz_step1'),
    path('panel/quiz/preview/', views.create_quiz_preview, name='create_quiz_preview'),
    re_path(r'^panel/quiz/(?P<quiz_slug>[\w\u0600-\u06FF%-]+)/publish/$', views.create_quiz_publish, name='create_quiz_publish'),
]
