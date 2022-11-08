from django.shortcuts import render, get_object_or_404, HttpResponse, redirect, reverse
from django.contrib.admin.views.decorators import staff_member_required
from django.template.loader import render_to_string
from django.contrib import messages
from django.http import JsonResponse

from submission import models
from identifiers import models as ident_models
from plugins.datacite import plugin_settings, forms, utils


@staff_member_required
def article_list(request):
    articles = models.Article.objects.filter(
        stage=models.STAGE_PUBLISHED,
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
            deposit_successful, text = utils.mint_datacite_doi(article, article.datacite_doi.identifier)
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
        models.Article,
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
            deposit_successful, text = utils.mint_datacite_doi(article, doi)

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
        models.Article,
        pk=article_id,
    )
    if article.get_doi():
        doi = article.get_doi()
    else:
        doi = '10.1234/example.doi',
    article_data = utils.prep_data(article, doi, '')
    return JsonResponse(article_data)
