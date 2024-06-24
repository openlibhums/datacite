from django.contrib import admin

from plugins.datacite import models


class SectionMintAdmin(admin.ModelAdmin):
    """Displays SectionMint objects in the Django admin interface."""
    list_display = ('journal',)
    list_filter = ('journal',)
    filter_horizontal = ('sections',)


admin_list = [
    (models.SectionMint, SectionMintAdmin),
]

[admin.site.register(*t) for t in admin_list]
