from django.urls import path, re_path
from . import views

urlpatterns = [
    path('', views.index_view, name='index'),

    # ── Public quiz pages ────────────────────────────────────────────────────
    re_path(r'^quiz/(?P<quiz_slug>[^/]+)/$',            views.quiz_view,        name='quiz_view'),
    re_path(r'^quiz/(?P<quiz_slug>[^/]+)/submit/$',     views.submit_score,     name='submit_score'),
    # re_path(r'^quiz/(?P<quiz_slug>[^/]+)/leaderboard/$',views.leaderboard_view, name='leaderboard_view'),

    # ── Public category lists ─────────────────────────────────────────────────
    path('bible/',    views.materials_list_client, {'category': 'bible'},    name='bible_list'),
    path('spiritual/',views.materials_list_client, {'category': 'spiritual'},name='spiritual_list'),
    path('iqraa/',    views.materials_list_client, {'category': 'iqraa'},    name='iqraa_list'),

    # ── Control Panel ─────────────────────────────────────────────────────────
    path('panel/',            views.panel_dashboard,  name='panel_dashboard'),
    path('panel/materials/',  views.manage_materials, name='manage_materials'),

    path('panel/materials/new/',     views.create_material_step1,    name='create_material_step1'),
    path('panel/materials/preview/', views.create_material_preview,  name='create_material_preview'),

    re_path(r'^panel/materials/(?P<quiz_slug>[^/]+)/edit/$',    views.create_material_step1,    name='edit_material'),
    re_path(r'^panel/materials/(?P<quiz_slug>[^/]+)/publish/$', views.create_material_publish,  name='create_material_publish'),
    re_path(r'^panel/materials/(?P<quiz_slug>[^/]+)/delete/$',  views.delete_material,          name='delete_material'),
    re_path(r'^panel/materials/(?P<quiz_slug>[^/]+)/toggle/$',  views.material_publish_toggle,  name='material_publish_toggle'),
    
    #badges
    # ── Badge Management Panel ──────────────────────────────────────────────
    path('panel/badges/',                 views.manage_badges,   name='manage_badges'),
    path('panel/badges/new/',             views.badge_create,    name='badge_create'),
    path('panel/badges/<int:badge_id>/edit/', views.badge_edit,      name='badge_edit'),
    path('panel/badges/<int:badge_id>/toggle/', views.badge_toggle,  name='badge_toggle'),
    path('panel/badges/<int:badge_id>/delete/', views.badge_delete,  name='badge_delete'),
    path('panel/badges/upload-api/', views.upload_badge_image_api, name='upload_badge_image_api'),
]