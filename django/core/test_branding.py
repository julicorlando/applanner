from io import BytesIO
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings
from PIL import Image

from accounts.models import User
from contenthub.models import BlogPost, PlatformHomepage
from tenants.models import Tenant


def picture(name="logo.png"):
    data=BytesIO()
    Image.new("RGB",(8,8),"#123456").save(data,format="PNG")
    return SimpleUploadedFile(name,data.getvalue(),content_type="image/png")


class BrandingTests(TestCase):
    def setUp(self):
        self.storage=TemporaryDirectory()
        self.addCleanup(self.storage.cleanup)
        settings_override=override_settings(MEDIA_ROOT=self.storage.name)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.master=User.objects.create_superuser(email="master-brand@example.com",password="StrongPassword!123")
        self.tenant=Tenant.objects.create(name="Empresa teste",slug="empresa-teste",public_enabled=True)

    def test_master_edits_homepage_and_news_publication(self):
        self.client.force_login(self.master)
        response=self.client.post("/master/pagina-inicial/",{
            "logo":picture(),"hero_title":"Título editado","hero_description":"Texto novo",
            "closing_title":"Chamada editada",
        })
        self.assertEqual(response.status_code,302)
        self.assertEqual(PlatformHomepage.objects.get(pk=1).hero_title,"Título editado")
        self.assertEqual(self.client.get("/imagens/logo/").status_code,200)
        post=BlogPost.objects.create(title="Notícia",slug="noticia",excerpt="Resumo",
            content="Corpo",status=BlogPost.Status.PUBLISHED,author=self.master,cover=picture("news.png"))
        self.client.logout()
        self.assertContains(self.client.get("/"),"Notícia")
        self.assertEqual(self.client.get(f"/imagens/noticia/{post.pk}/").status_code,200)
        post.status=BlogPost.Status.DRAFT
        post.save()
        self.assertEqual(self.client.get(f"/imagens/noticia/{post.pk}/").status_code,404)

    def test_official_logo_is_default_and_master_upload_can_override_it(self):
        self.assertIsNotNone(finders.find("images/applanner-logo.png"))
        self.assertContains(self.client.get("/"),'class="platform-logo platform-logo-official"')
        self.client.force_login(self.master)
        self.assertContains(self.client.get("/master/pagina-inicial/"),"Logo oficial do ApPlanner ativa")
        self.client.post("/master/pagina-inicial/",{"logo":picture(),"hero_title":"Título",
            "hero_description":"Descrição","closing_title":"Chamada"})
        response=self.client.get("/")
        self.assertContains(response,'class="platform-logo platform-logo-custom"')
        self.assertContains(response,"/imagens/logo/")

    def test_private_unauthorized_branding_and_public_only_image(self):
        staff=User.objects.create_user(email="other-brand@example.com",password="StrongPassword!123")
        self.client.force_login(staff)
        self.assertEqual(self.client.get("/master/pagina-inicial/").status_code,403)
        self.assertEqual(self.client.get("/app/minha-pagina/").status_code,403)
        self.tenant.logo=picture()
        self.tenant.save()
        self.client.logout()
        self.assertEqual(self.client.get(f"/imagens/empresa/{self.tenant.pk}/logo/").status_code,200)
        self.assertEqual(self.client.get(f"/imagens/empresa/{self.tenant.pk}/metadata/").status_code,404)
        self.tenant.public_enabled=False
        self.tenant.save()
        self.assertEqual(self.client.get(f"/imagens/empresa/{self.tenant.pk}/logo/").status_code,404)
