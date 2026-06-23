from django.urls import path, re_path
from . import views

urlpatterns = [
    path('', views.index_view, name='index'),
    
    # Public Client Content Pages
    path('quiz/<str:quiz_slug>/', views.quiz_view, name='quiz_view'), # 👈 تم إضافة المسار هنا ليطابق دالة الـ View
    path('bible/', views.materials_list_client, {'category': 'bible'}, name='bible_list'),
    path('spiritual/', views.materials_list_client, {'category': 'spiritual'}, name='spiritual_list'),
    path('iqraa/', views.materials_list_client, {'category': 'iqraa'}, name='iqraa_list'),
    
    # Control Panel Management
    path('panel/', views.panel_dashboard, name='panel_dashboard'),
    path('panel/materials/', views.manage_materials, name='manage_materials'),
    
    path('panel/materials/new/', views.create_material_step1, name='create_material_step1'),
    re_path(r'^panel/materials/(?P<quiz_slug>[^/]+)/edit/$', views.create_material_step1, name='edit_material'),
    
    path('panel/materials/preview/', views.create_material_preview, name='create_material_preview'),
    re_path(r'^panel/materials/(?P<quiz_slug>[^/]+)/publish/$', views.create_material_publish, name='create_material_publish'),
    re_path(r'^panel/materials/(?P<quiz_slug>[^/]+)/delete/$', views.delete_material, name='delete_material'),
    re_path(r'^panel/materials/(?P<quiz_slug>[^/]+)/toggle/$', views.material_publish_toggle, name='material_publish_toggle'),
    # re_path(r'^quiz/(?P<quiz_slug>[^/]+)/$', views.quiz_view, name='quiz_view'),
    re_path(r'^quiz/(?P<quiz_slug>[^/]+)/leaderboard/$', views.leaderboard_view, name='leaderboard_view'),
]