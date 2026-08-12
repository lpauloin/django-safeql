"""
Sample schema used only by django-safeql's own test suite.

It models a small, generic library catalog (publishers, authors, books,
awards) so the tests and README examples don't depend on any particular
downstream application's data model.
"""

from django.db import models


class Publisher(models.Model):
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    uuid = models.UUIDField(null=True, blank=True)

    class Meta:
        app_label = "testapp"


class Author(models.Model):
    name = models.CharField(max_length=200)
    publisher = models.ForeignKey(Publisher, on_delete=models.CASCADE, related_name="authors", null=True)

    class Meta:
        app_label = "testapp"


class Award(models.Model):
    name = models.CharField(max_length=200)
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="award_set")
    year = models.IntegerField(null=True)
    category = models.CharField(max_length=100, blank=True)
    is_official = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=True)

    class Meta:
        app_label = "testapp"


class Book(models.Model):
    title = models.CharField(max_length=200)
    isbn = models.CharField(max_length=32, blank=True)
    status = models.CharField(max_length=32, default="draft")
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="books", null=True)
    publisher = models.ForeignKey(Publisher, on_delete=models.CASCADE, related_name="books", null=True)
    pages = models.IntegerField(null=True)
    price = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    created = models.DateTimeField(auto_now_add=True)
    published_at = models.DateField(null=True)
    # Secondary numeric metrics, used to exercise aggregates/comparisons in tests.
    print_run = models.IntegerField(default=0)
    review_count = models.IntegerField(default=0)
    word_count = models.IntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        app_label = "testapp"
