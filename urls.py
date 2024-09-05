from django.urls import re_path

from plugins.datacite import views


urlpatterns = [
    re_path(
        r'^articles/$',
        views.article_list,
        name='datacite_articles',
    ),
    re_path(
        r'^articles/export/(?P<article_id>\d+)/$',
        views.article_export,
        name='datacite_article_export',
    ),
    re_path(
        r'^articles/(?P<article_id>\d+)/mint/$',
        views.add_doi,
        name='datacite_add_doi',
    ),
]
