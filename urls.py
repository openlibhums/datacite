from django.conf.urls import url

from plugins.datacite import views


urlpatterns = [
    url(r'^articles/$', views.article_list, name='datacitexml_articles'),
    url(r'^articles/export/(?P<article_id>\d+)/$', views.article_export, name='datacitexml_article_export'),
    url(r'^articles/(?P<article_id>\d+)/mint/$', views.add_doi, name='datacitexml_add_doi'),
]
