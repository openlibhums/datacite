from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect, reverse
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.http import JsonResponse
from django.utils.http import url_has_allowed_host_and_scheme

from submission import models as submission_models
from identifiers import models as ident_models
from plugins.datacite import plugin_settings, forms, utils, models
from core import forms as core_forms
from journal.models import Journal
from security.decorators import has_journal
from utils import setting_handler


def configuration_context(request):
    return {
        'datacite_configured': utils.is_configured(),
        'debug_mode': settings.DEBUG,
        'test_journal': (
            request.journal.status == Journal.PublishingStatus.TEST
        ),
    }


@has_journal
@staff_member_required
def index(request):
    articles = get_doi_articles(request.journal)
    section_mint = models.SectionMint.objects.filter(
        journal=request.journal,
    ).first()
    template = 'datacite/index.html'
    context = {
        'auto_deposit_enabled': utils.auto_deposit_enabled(request.journal),
        'minting_sections': (
            section_mint.sections.all() if section_mint else None
        ),
        'articles_count': articles.count(),
        'missing_doi_count': articles.exclude(
            identifier__id_type='doi',
        ).count(),
        **configuration_context(request),
    }
    return render(request, template, context)


def safe_next_url(request, default):
    """
    Returns the ``next`` URL from the request when it is safe to redirect to.
    """
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return default


def return_to_article(request, article):
    """
    Redirects back to the article list, keeping the editor's filters and
    scrolling to the article they acted on.
    """
    url = safe_next_url(request, reverse('datacite_articles'))
    return redirect('{}#article-{}'.format(url.split('#')[0], article.pk))


def get_doi_articles(journal):
    # This filter ensures that articles have at least been accepted and have
    # not subsequently been moved back a stage.
    return submission_models.Article.objects.filter(
        journal=journal,
        date_declined__isnull=True,
        date_accepted__isnull=False,
    ).exclude(
        stage__in=[
            submission_models.STAGE_ARCHIVED,
            submission_models.STAGE_UNSUBMITTED,
            submission_models.STAGE_UNASSIGNED,
            submission_models.STAGE_UNDER_REVIEW,
            submission_models.STAGE_UNDER_REVISION,
            submission_models.STAGE_REJECTED
        ]
    )


@has_journal
@staff_member_required
def article_list(request):
    articles = get_doi_articles(request.journal)

    if request.method == 'POST' and plugin_settings.REDEPOSIT_BUTTON:
        article = get_object_or_404(
            articles,
            pk=request.POST.get('article_id'),
        )
        datacite_doi = article.get_doi()

        if datacite_doi:
            event = utils.deposit_event(article)
            deposit_successful, text = utils.mint_datacite_doi(
                article,
                datacite_doi,
                event,
            )
            if deposit_successful:
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'DOI {} re-deposited as {}.'.format(
                        datacite_doi,
                        'findable' if event == 'publish' else 'a draft',
                    ),
                )
            else:
                messages.add_message(
                    request,
                    messages.ERROR,
                    'DOI {} was not re-deposited. DataCite said: {}'.format(
                        datacite_doi,
                        text,
                    ),
                )
        return return_to_article(request, article)

    filter_form = forms.ArticleFilterForm(
        request.GET or None,
        articles=articles,
    )
    if filter_form.is_valid():
        articles = filter_form.filter(articles)

    articles = articles.select_related(
        'correspondence_author',
        'section',
    ).prefetch_related(
        Prefetch(
            'identifier_set',
            queryset=ident_models.Identifier.objects.filter(id_type='doi'),
            to_attr='doi_identifiers',
        )
    ).order_by('-date_accepted', '-pk')

    paginate_by = request.GET.get('paginate_by', '25')
    if paginate_by == 'all':
        page_obj = None
    else:
        if paginate_by not in ('10', '25', '50', '100'):
            paginate_by = '25'
        page_obj = Paginator(articles, int(paginate_by)).get_page(
            request.GET.get('page'),
        )
        articles = page_obj.object_list

    for article in articles:
        article.datacite_doi = next(iter(article.doi_identifiers), None)
        article.findable = utils.deposit_event(article) == 'publish'
        if article.datacite_doi:
            article.fabrica_url = utils.get_fabrica_url(
                request.journal,
                article.datacite_doi.identifier,
            )

    template = 'datacite/article_list.html'
    context = {
        'articles': articles,
        'filter_form': filter_form,
        'page_obj': page_obj,
        'is_paginated': bool(page_obj and page_obj.has_other_pages()),
        'paginate_by': paginate_by,
        'redeposit_button': plugin_settings.REDEPOSIT_BUTTON,
        **configuration_context(request),
    }

    return render(request, template, context)


@has_journal
@staff_member_required
def add_doi(request, article_id):
    """
    Allows an editor to add a DOI to an article and mint it.
    """
    article = get_object_or_404(
        submission_models.Article,
        pk=article_id,
        journal=request.journal,
    )
    if article.get_doi():
        messages.add_message(
            request,
            messages.WARNING,
            'Article {} already has a DOI.'.format(article.pk),
        )
        return return_to_article(request, article)

    form = forms.DOIForm(
        article=article,
        initial={
            'identifier': utils.generate_doi(article),
            'findable': True,
        }
    )
    if request.method == 'POST':
        form = forms.DOIForm(
            request.POST,
            article=article,
        )
        if form.is_valid():
            doi = form.cleaned_data.get('identifier')
            event = form.event
            deposit_successful, text = utils.mint_datacite_doi(
                article,
                doi,
                event=event,
            )

            if deposit_successful:
                form.save()
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'DOI {} deposited as {}.'.format(
                        doi,
                        'findable' if event == 'publish' else 'a draft',
                    ),
                )
                return return_to_article(request, article)
            else:
                messages.add_message(
                    request,
                    messages.ERROR,
                    'DOI was not minted. DataCite said: {}'.format(text),
                )
    template = 'datacite/add_doi.html'
    context = {
        'article': article,
        'prefix': plugin_settings.DATACITE_PREFIX,
        'form': form,
        'next_url': safe_next_url(request, reverse('datacite_articles')),
        **configuration_context(request),
    }
    return render(
        request,
        template,
        context
    )


@has_journal
@staff_member_required
def article_export(request, article_id):
    """
    Generates and serves a Datacite JSON.
    """
    article = get_object_or_404(
        submission_models.Article,
        pk=article_id,
        journal=request.journal,
    )
    doi = article.get_doi() or utils.generate_doi(article)
    article_data = utils.prep_data(article, doi, '')
    return JsonResponse(article_data)


@has_journal
@staff_member_required
def manager(request):
    """
    Presents a management form for plugin settings.
    """
    settings = utils.get_settings(request.journal)
    manager_form = core_forms.GeneratedSettingForm(
        settings=settings
    )
    if request.POST:
        manager_form = core_forms.GeneratedSettingForm(
            request.POST,
            settings=settings,
        )
        if manager_form.is_valid():
            manager_form.save(
                group='plugin:datacite',
                journal=request.journal,
            )
            messages.add_message(
                request,
                messages.SUCCESS,
                'Form saved.',
            )
            return redirect(
                reverse('datacite_manager')
            )

    template = 'datacite/manager.html'
    context = {
        'manager_form': manager_form,
    }
    return render(
        request,
        template,
        context,
    )


@has_journal
@staff_member_required
def section_mint_manager(request):
    try:
        section_mint = models.SectionMint.objects.get(
            journal=request.journal
        )
    except models.SectionMint.DoesNotExist:
        section_mint = None

    form = forms.SectionMintForm(
        instance=section_mint,
        request_journal=request.journal,
    )
    if request.method == 'POST':
        form = forms.SectionMintForm(
            request.POST,
            instance=section_mint,
            request_journal=request.journal,
        )
        if form.is_valid():
            form.save()
            messages.add_message(
                request,
                messages.SUCCESS,
                'Section controls saved.',
            )
            return redirect('datacite_section_mint_manager')

    template = 'datacite/section_mint_form.html'
    context = {
        'form': form,
        'auto_mint_is_enabled': setting_handler.get_setting(
            setting_group_name='plugin:datacite',
            setting_name='enable_datacite_auto',
            journal=request.journal,
        ).processed_value
    }
    return render(
        request,
        template,
        context,
    )
