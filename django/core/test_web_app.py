from io import BytesIO
from tempfile import TemporaryDirectory
from PIL import Image
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from contenthub.models import PlatformHomepage
from accounts.models import User
from tenants.models import Tenant


@override_settings(STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},
                            'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class WebAppTests(TestCase):
    def setUp(self):
        directory=TemporaryDirectory();self.addCleanup(directory.cleanup)
        settings=override_settings(MEDIA_ROOT=directory.name);settings.enable();self.addCleanup(settings.disable)

    def test_manifest_has_same_origin_entry_and_installation_sizes(self):
        response=self.client.get(reverse('web-app-manifest'),{'next':'https://example.com/'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['Content-Type'],'application/manifest+json')
        data=response.json()
        self.assertEqual(data['start_url'],'/')
        self.assertEqual(data['scope'],'/')
        self.assertEqual(data['display'],'standalone')
        self.assertEqual({item['sizes'] for item in data['icons']},{'192x192','512x512'})
        for item in data['icons']:
            response=self.client.get(item['src'])
            self.assertEqual(response.status_code,200)
            image=Image.open(BytesIO(response.content))
            self.assertEqual(f'{image.width}x{image.height}',item['sizes'])

    def test_launcher_icon_uses_master_favicon_without_stretching(self):
        output=BytesIO();Image.new('RGB',(80,40),'red').save(output,format='PNG')
        PlatformHomepage.objects.create(pk=1,favicon=SimpleUploadedFile('icon.png',output.getvalue(),content_type='image/png'))
        response=self.client.get(reverse('web-app-icon',args=[192]))
        image=Image.open(BytesIO(response.content))
        self.assertEqual(image.size,(192,192))
        self.assertEqual(image.getpixel((96,96)),(255,0,0))
        self.assertEqual(image.getpixel((0,0)),(245,247,250))
        # A wide source stays wide inside the square canvas, rather than stretching vertically.
        self.assertEqual(image.getpixel((96,40)),(245,247,250))
        self.assertEqual(response['X-Content-Type-Options'],'nosniff')

    def test_apple_icon_and_invalid_size(self):
        response=self.client.get(reverse('web-app-icon',args=[180]))
        self.assertEqual(Image.open(BytesIO(response.content)).size,(180,180))
        self.assertEqual(self.client.get(reverse('web-app-icon',args=[99999])).status_code,404)

    def test_missing_uploaded_icon_falls_back_to_official(self):
        PlatformHomepage.objects.create(pk=1,favicon='platform/deleted.png')
        self.assertEqual(self.client.get(reverse('web-app-icon',args=[512])).status_code,200)

    @override_settings(SUBSCRIPTION_ACCESS_ENFORCED=True)
    def test_installation_assets_remain_available_when_subscription_is_locked(self):
        company=Tenant.objects.create(name='Company',slug='web-app-lock')
        user=User.objects.create_user(email='web-app@test.example',tenant=company,role='owner')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('web-app-manifest')).status_code,200)
        self.assertEqual(self.client.get(reverse('web-app-icon',args=[192])).status_code,200)
        response=self.client.get(reverse('portal-home'))
        self.assertRedirects(response,reverse('billing-subscription-status'),fetch_redirect_response=False)

    def test_base_template_exposes_manifest_and_apple_install_metadata(self):
        response=self.client.get('/')
        self.assertContains(response,'rel="manifest"')
        self.assertContains(response,reverse('web-app-manifest'))
        self.assertContains(response,'apple-touch-icon')
        self.assertContains(response,'viewport-fit=cover')
        self.assertContains(response,'apple-mobile-web-app-capable')
