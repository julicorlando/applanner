from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class BlogPost(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT="draft","Rascunho"
        PUBLISHED="published","Publicado"
        ARCHIVED="archived","Arquivado"

    title=models.CharField(max_length=180)
    slug=models.SlugField(max_length=190,unique=True)
    excerpt=models.CharField(max_length=320)
    content=models.TextField()
    cover=models.ImageField(upload_to="blog/",blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.DRAFT,db_index=True)
    featured=models.BooleanField(default=False)
    meta_title=models.CharField(max_length=180,blank=True)
    meta_description=models.CharField(max_length=320,blank=True)
    author=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="blog_posts")
    published_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        indexes=[models.Index(fields=["status","published_at"],name="content_blog_public_idx")]


class LandingPage(TimeStampedModel):
    slug=models.SlugField(max_length=120)
    locale=models.CharField(max_length=10,default="pt-br")
    segment=models.CharField(max_length=40,blank=True)
    headline=models.CharField(max_length=160)
    subheadline=models.CharField(max_length=320,blank=True)
    body=models.TextField(blank=True)
    cta_label=models.CharField(max_length=60,blank=True)
    cta_url=models.CharField(max_length=255,blank=True)
    seo_title=models.CharField(max_length=70,blank=True)
    seo_description=models.CharField(max_length=180,blank=True)
    active=models.BooleanField(default=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["slug","locale"],name="uq_landing_locale")]
