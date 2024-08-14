from django.db import models


class SectionMint(models.Model):
    journal = models.OneToOneField(
        'journal.Journal',
        on_delete=models.CASCADE,
    )
    sections = models.ManyToManyField(
        'submission.Section',
        blank=True,
    )

    def __str__(self):
        return f'{self.journal} mints DOIs for ' \
               f'{self.sections.count()} sections'
