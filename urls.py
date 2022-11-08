from django.conf.urls import url

from plugins.datacite import views


urlpatterns = [
    url(r'^articles/$', views.article_list, name='datacite_articles'),
    url(r'^articles/export/(?P<article_id>\d+)/$', views.article_export, name='datacite_article_export'),
    url(r'^articles/(?P<article_id>\d+)/mint/$', views.add_doi, name='datacite_add_doi'),
]
