from django.urls import re_path
from django.views.generic import TemplateView

from plugins.datacite import views

urlpatterns = [
    re_path(
        r'^$',
        TemplateView.as_view(template_name="datacite/index.html"),
        name='datacite_index',
    ),
    re_path(r'^manager/$', views.manager, name='datacite_manager'),
    re_path(r'^articles/$', views.article_list, name='datacite_articles'),
    re_path(r'^articles/export/(?P<article_id>\d+)/$', views.article_export,
            name='datacite_article_export'),
    re_path(r'^articles/(?P<article_id>\d+)/mint/$', views.add_doi,
            name='datacite_add_doi'),
    re_path(r'^sections/$', views.section_mint_manager,
            name='datacite_section_mint_manager'),
]
