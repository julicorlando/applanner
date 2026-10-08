"""Installable application metadata. No offline copy of account or payment data."""
from io import BytesIO
from django.contrib.staticfiles import finders
from django.http import Http404, HttpResponse, JsonResponse
from django.urls import reverse
from PIL import Image, ImageOps, UnidentifiedImageError
from contenthub.models import PlatformHomepage


def manifest(request):
    branding=PlatformHomepage.objects.filter(pk=1).first()
    version=str(int(branding.updated_at.timestamp())) if branding else '1'
    response=JsonResponse({
        'id':'/', 'name':'ApPlanner', 'short_name':'ApPlanner', 'lang':'pt-BR',
        'description':'Sua agenda, equipe e gestão no celular.',
        'start_url':reverse('home'), 'scope':'/', 'display':'standalone',
        'background_color':'#f5f7fa', 'theme_color':'#f5f7fa',
        'icons':[{'src':reverse('web-app-icon',args=[size])+f'?v={version}',
                  'sizes':f'{size}x{size}','type':'image/png','purpose':'any maskable'} for size in (192,512)],
    },content_type='application/manifest+json')
    response['Cache-Control']='public, max-age=300'
    return response


def icon(request,size):
    if size not in {180,192,512}: raise Http404
    branding=PlatformHomepage.objects.filter(pk=1).first()
    source=branding.favicon if branding and branding.favicon else None
    def render(source):
        with Image.open(source) as image:
            # Leave the identity inside the circular safe area used by mobile launchers.
            artwork=ImageOps.contain(ImageOps.exif_transpose(image).convert('RGBA'),(int(size*.56),int(size*.56)),Image.Resampling.LANCZOS)
            canvas=Image.new('RGBA',(size,size),'#f5f7fa')
            canvas.alpha_composite(artwork,((size-artwork.width)//2,(size-artwork.height)//2))
            output=BytesIO();canvas.convert('RGB').save(output,format='PNG')
            return output.getvalue()
    try:
        if source:
            with source.open('rb') as stream: data=render(stream)
        else: data=render(finders.find('images/applanner-logo.png'))
    except (OSError,ValueError,UnidentifiedImageError):
        try: data=render(finders.find('images/applanner-logo.png'))
        except (OSError,ValueError,UnidentifiedImageError): raise Http404 from None
    response=HttpResponse(data,content_type='image/png')
    response['Cache-Control']='public, max-age=300'
    response['X-Content-Type-Options']='nosniff'
    return response


def worker(request):
    path=finders.find('js/app-worker.js')
    if not path: raise Http404
    with open(path,encoding='utf-8') as source:
        response=HttpResponse(source.read(),content_type='application/javascript')
    response['Cache-Control']='no-cache'
    response['Service-Worker-Allowed']='/'
    response['X-Content-Type-Options']='nosniff'
    return response
