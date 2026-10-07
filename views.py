from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect, reverse
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.db.models import Prefetch
from django.http import JsonResponse

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
    template = 'datacite/index.html'
    context = configuration_context(request)
    return render(request, template, context)


@has_journal
@staff_member_required
def article_list(request):
    # This filter is a pain but ensures that articles have at least been accepted
    # and have not subsequently been moved back a stage.
    articles = submission_models.Article.objects.filter(
        journal=request.journal,
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
    ).prefetch_related(
        Prefetch(
            'identifier_set',
            queryset=ident_models.Identifier.objects.filter(id_type='doi'),
            to_attr='doi_identifiers',
        )
    )

    for article in articles:
        article.datacite_doi = next(iter(article.doi_identifiers), None)

    if request.POST and plugin_settings.REDEPOSIT_BUTTON:
        article_id = request.POST.get('article_id')
        article = get_object_or_404(articles, pk=article_id)
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
                return redirect(
                    reverse(
                        'datacite_articles',
                    )
                )
            else:
                messages.add_message(
                    request,
                    messages.ERROR,
                    'DOI was not minted. DataCite said: {}'.format(text),
                )

    template = 'datacite/article_list.html'
    context = {
        'articles': articles,
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
    datacite_doi = ident_models.Identifier.objects.filter(
        article=article,
        id_type='doi',
    ).first()
    if datacite_doi:
        messages.add_message(
            request,
            messages.WARNING,
            'Article {} already has a DOI'.format(article.pk),
        )
        return redirect(
            reverse(
                'datacite_articles'
            )
        )
    form = forms.DOIForm(
        article=article,
        initial={
            'identifier': utils.generate_doi(article),
            'findable': utils.deposit_event(article) == 'publish',
        }
    )
    if request.POST:
        form = forms.DOIForm(
            request.POST,
            article=article,
        )
        if form.is_valid():
            doi = form.cleaned_data.get('identifier')
            findable = form.cleaned_data.get('findable')
            deposit_successful, text = utils.mint_datacite_doi(
                article,
                doi,
                event='publish' if findable else 'register',
            )

            if deposit_successful:
                form.save()
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'DOI Added.',
                )
                return redirect(
                    reverse(
                        'datacite_articles',
                    )
                )
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
