from django import forms

from identifiers import models as im


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
