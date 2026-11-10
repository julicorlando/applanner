import io
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile

from .models import SocialCampaign, SocialCampaignMedia


class SocialCampaignForm(forms.ModelForm):
    class Meta:
        model=SocialCampaign
        fields=['name','channel','paid','objective','headline','description','caption']
        labels={'name':'Nome interno','channel':'Rede social','paid':'Usar em anúncio pago (planejamento)',
                'objective':'Objetivo','headline':'Título da página de captação','description':'Apresentação da campanha',
                'caption':'Legenda para a publicação'}
        widgets={'description':forms.Textarea(attrs={'rows':4}),'caption':forms.Textarea(attrs={'rows':5})}


class SocialMediaForm(forms.ModelForm):
    rights=forms.BooleanField(label='Tenho autorização para usar e divulgar esta mídia.')

    class Meta:
        model=SocialCampaignMedia
        fields=['title','placement','file']
        labels={'title':'Descrição acessível da mídia','placement':'Formato','file':'Imagem ou vídeo'}
        widgets={'file':forms.ClearableFileInput(attrs={'accept':'image/jpeg,image/png,image/webp,video/mp4'})}

    def clean_file(self):
        file=self.cleaned_data['file']
        suffix=Path(file.name).suffix.lower()
        if not file.size or file.size>40*1024*1024:
            raise forms.ValidationError('Envie um arquivo de até 40 MB (imagens: até 10 MB).')
        if suffix=='.mp4':
            header=file.read(64)
            file.seek(0)
            if len(header)<16 or header[4:8]!=b'ftyp' or header[8:12] not in (b'isom',b'iso2',b'iso4',b'iso5',b'iso6',b'mp41',b'mp42',b'avc1',b'dash',b'M4V '):
                raise forms.ValidationError('O arquivo não é um MP4 reconhecido.')
            self.media_info={'content_type':'video/mp4','width':0,'height':0}
            return file
        if suffix not in ('.jpg','.jpeg','.png','.webp') or file.size>10*1024*1024:
            raise forms.ValidationError('Use JPG, PNG ou WebP de até 10 MB, ou vídeo MP4 de até 40 MB.')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                image=Image.open(file)
                if image.width*image.height>20_000_000:
                    raise ValueError('image size')
                image.verify()
                file.seek(0)
                image=ImageOps.exif_transpose(Image.open(file)).convert('RGB')
                image.thumbnail((4096,4096))
                output=io.BytesIO()
                image.save(output,format='JPEG',quality=90,optimize=True)
                self.media_info={'content_type':'image/jpeg','width':image.width,'height':image.height}
                return SimpleUploadedFile('creative.jpg',output.getvalue(),content_type='image/jpeg')
        except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
            raise forms.ValidationError('Não foi possível ler a imagem. Envie uma imagem válida de até 20 megapixels.')


class CampaignContactForm(forms.Form):
    name=forms.CharField(max_length=160,label='Seu nome',widget=forms.TextInput(attrs={'autocomplete':'name'}))
    business=forms.CharField(max_length=100,label='Nome do negócio ou segmento')
    email=forms.EmailField(label='E-mail',max_length=254,widget=forms.EmailInput(attrs={'autocomplete':'email'}))
    phone=forms.CharField(max_length=30,label='WhatsApp com DDD',widget=forms.TextInput(attrs={'type':'tel','autocomplete':'tel','inputmode':'tel'}))
    consent=forms.BooleanField(label='Quero receber contato sobre o ApPlanner e li a Política de Privacidade.')
    marketing=forms.BooleanField(required=False,label='Também autorizo o uso deste evento para medir campanhas na Meta.')
    website=forms.CharField(required=False,widget=forms.HiddenInput)

    def clean_phone(self):
        from re import sub
        phone=sub(r'\D','',self.cleaned_data['phone'])
        if len(phone) in (10,11):
            phone='55'+phone
        if not phone.startswith('55') or len(phone) not in (12,13):
            raise forms.ValidationError('Informe um WhatsApp brasileiro válido com DDD.')
        return phone
