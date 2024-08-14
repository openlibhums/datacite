from django import forms

from plugins.datacite import models
from identifiers import models as im
from submission import models as sm


class DOIForm(forms.ModelForm):

    class Meta:
        model = im.Identifier
        fields = ('identifier',)

    def __init__(self, *args, **kwargs):
        self.article = kwargs.pop('article')
        self.id_type = 'doi'
        super(DOIForm, self).__init__(*args, **kwargs)

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