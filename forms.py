from django import forms
from django.db.models import Q

from plugins.datacite import models, plugin_settings, utils
from identifiers import models as im
from submission import models as sm


class DOIForm(forms.ModelForm):
    findable = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Marks the DOI as findable. Leave unchecked to register a "
                  "draft DOI.",
    )

    class Meta:
        model = im.Identifier
        fields = ('identifier',)

    def __init__(self, *args, **kwargs):
        self.article = kwargs.pop('article')
        self.id_type = 'doi'
        super(DOIForm, self).__init__(*args, **kwargs)
        # Only published articles can have a findable DOI.
        if utils.deposit_event(self.article) != 'publish':
            del self.fields['findable']

    @property
    def event(self):
        if self.cleaned_data.get('findable'):
            return 'publish'
        return 'register'

    def clean_identifier(self):
        doi = self.cleaned_data.get('identifier', '').strip()
        prefix = plugin_settings.DATACITE_PREFIX
        if prefix and not doi.startswith('{}/'.format(prefix)):
            raise forms.ValidationError(
                'The DOI must start with this installation\'s DataCite '
                'prefix, {}/.'.format(prefix)
            )
        if im.Identifier.objects.filter(
            id_type=self.id_type,
            identifier=doi,
        ).exists():
            raise forms.ValidationError(
                'This DOI is already in use by another article.'
            )
        return doi

    def save(self, commit=True):
        identifier = super(DOIForm, self).save(commit=False)
        identifier.article = self.article
        identifier.id_type = self.id_type

        if commit:
            identifier.save()

        return identifier


class SectionMintForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.journal = kwargs.pop('request_journal', None)
        super().__init__(*args, **kwargs)
        if self.journal:
            self.fields['sections'].queryset = sm.Section.objects.filter(
                journal=self.journal,
            )

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.journal:
            instance.journal = self.journal
        if commit:
            instance.save()
            self.save_m2m()
        return instance

    class Meta:
        model = models.SectionMint
        fields = ['sections']
        widgets = {
            'sections': forms.CheckboxSelectMultiple,
        }

class ArticleFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        label='Search',
        widget=forms.TextInput(
            attrs={
                'type': 'search',
                'placeholder': 'Title, article ID or DOI',
            },
        ),
    )
    doi = forms.ChoiceField(
        required=False,
        label='DOI',
        choices=[
            ('', 'Any'),
            ('missing', 'No DOI'),
            ('present', 'Has a DOI'),
        ],
    )
    status = forms.ChoiceField(
        required=False,
        label='Status',
        choices=[
            ('', 'Any'),
            ('unpublished', 'Not yet published (draft DOI)'),
            ('published', 'Published (findable DOI)'),
        ],
    )
    stage = forms.ChoiceField(
        required=False,
        label='Stage',
        choices=[('', 'Any')],
    )

    def __init__(self, *args, **kwargs):
        articles = kwargs.pop('articles')
        super().__init__(*args, **kwargs)
        stage_labels = dict(sm.Article._meta.get_field('stage').choices)
        stages = articles.order_by('stage').values_list(
            'stage',
            flat=True,
        ).distinct()
        self.fields['stage'].choices = [('', 'Any')] + [
            (stage, stage_labels.get(stage, stage)) for stage in stages
        ]

    def filter(self, articles):
        q = self.cleaned_data.get('q', '').strip()
        if q:
            query = Q(title__icontains=q) | Q(
                identifier__id_type='doi',
                identifier__identifier__icontains=q,
            )
            if q.isdigit():
                query |= Q(pk=int(q))
            articles = articles.filter(query).distinct()

        doi = self.cleaned_data.get('doi')
        has_doi = Q(identifier__id_type='doi')
        if doi == 'missing':
            articles = articles.exclude(has_doi)
        elif doi == 'present':
            articles = articles.filter(has_doi).distinct()

        status = self.cleaned_data.get('status')
        if status == 'published':
            articles = articles.filter(stage=sm.STAGE_PUBLISHED)
        elif status == 'unpublished':
            articles = articles.exclude(stage=sm.STAGE_PUBLISHED)

        stage = self.cleaned_data.get('stage')
        if stage:
            articles = articles.filter(stage=stage)

        return articles
