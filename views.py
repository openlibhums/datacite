from django.shortcuts import render, get_object_or_404, redirect, reverse
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import JsonResponse

from submission import models as submission_models
from identifiers import models as ident_models
from plugins.datacite import plugin_settings, forms, utils, models
from core import forms as core_forms
from security.decorators import has_journal
from utils import setting_handler


@staff_member_required
def article_list(request):
    articles = submission_models.Article.objects.filter(
        journal=request.journal,
    )
    for article in articles:
        article.datacite_doi = ident_models.Identifier.objects.filter(
            article=article,
            id_type='doi',
        ).first()

    if request.POST:
        article_id = request.POST.get('article_id')
        article = articles.get(pk=article_id)
        article.datacite_doi = ident_models.Identifier.objects.filter(
            article=article,
            id_type='doi',
        ).first()

        if article.datacite_doi:
            deposit_successful, text = utils.mint_datacite_doi(
                article,
                article.datacite_doi.identifier,
                'publish',
            )
            if deposit_successful:
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
                    'DOI was not minted.<br />{}'.format(text),
                )

    template = 'datacite/article_list.html'
    context = {
        'articles': articles,
        'redeposit_button': plugin_settings.REDEPOSIT_BUTTON,
    }

    return render(request, template, context)


@staff_member_required
def add_doi(request, article_id):
    """
    Allows an editor to add a DOI to an article and mint it.
    """
    article = get_object_or_404(
        submission_models.Article,
        pk=article_id,
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
            'identifier': "{prefix}/{journal_code}.".format(
                prefix=plugin_settings.DATACITE_PREFIX,
                journal_code=request.journal.code if plugin_settings.JOURNAL_PREFIX else '',
            ),
        }
    )
    if request.POST:
        form = forms.DOIForm(
            request.POST,
            article=article,
        )
        if form.is_valid():
            doi = form.cleaned_data.get('identifier')
            deposit_successful, text = utils.mint_datacite_doi(
                article,
                doi,
                event='publish'
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
                    'DOI was not minted.<br />{}'.format(text),
                )
    template = 'datacite/add_doi.html'
    context = {
        'article': article,
        'prefix': plugin_settings.DATACITE_PREFIX,
        'form': form,
    }
    return render(
        request,
        template,
        context
    )


@staff_member_required
def article_export(request, article_id):
    """
    Generates and serves a Datacite JSON.
    """
    article = get_object_or_404(
        submission_models.Article,
        pk=article_id,
    )
    if article.get_doi():
        doi = article.get_doi()
    else:
        doi = '10.1234/example.doi',
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
