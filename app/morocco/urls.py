from django.conf.urls import url
from . import views

app_name = 'morocco'
urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^snapshots/', views.IndexView.as_view(), name='snapshots'),
    url(r'^snapshot/(?P<sha>[a-z0-9]+)$', views.snapshot, name='snapshot'),
    url(r'^sync/snapshots/', views.sync_snapshots, name='sync_snapshots'),
    url(r'^update/snapshots/(?P<sha>[a-z0-9]+)$', views.UpdateSnapshot.as_view(), name='update_snapshot'),
    url(r'^api/snapshot/(?P<sha>[a-z0-9]+)$', views.ApiUpdateSnapshot.as_view(), name='api_update_snapshot'),
    url(r'^manager/', views.manager, name='manager')
]
