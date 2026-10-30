"""DICOM Part 10 headers are parsed without decoding or publishing pixel data."""
from io import BytesIO
from pathlib import Path
import warnings
from django.core.exceptions import ValidationError
from pydicom import dcmread
from pydicom.uid import UID
from .clinical import validate_document_upload as validate_standard_upload


def validate_document_upload(*, upload):
    if Path(upload.name).suffix.lower() != '.dcm':
        return validate_standard_upload(upload=upload)
    if upload.size > 10 * 1024 * 1024:
        raise ValidationError('O DICOM deve ter até 10 MB.')
    raw = upload.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024 or raw[128:132] != b'DICM':
        raise ValidationError('Envie um arquivo DICOM Part 10 válido.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            ds = dcmread(BytesIO(raw), force=False, stop_before_pixels=True, specific_tags=['SOPClassUID', 'SOPInstanceUID'])
            meta = ds.file_meta
            if not UID(meta.TransferSyntaxUID).is_transfer_syntax:
                raise ValueError()
            for key, meta_key in [('SOPClassUID','MediaStorageSOPClassUID'),('SOPInstanceUID','MediaStorageSOPInstanceUID')]:
                value = str(getattr(ds, key))
                if not UID(value).is_valid or value != str(getattr(meta, meta_key)):
                    raise ValueError()
    except Exception as exc:
        raise ValidationError('Cabeçalho DICOM ausente, inválido ou inconsistente.') from exc
    return raw, 'application/dicom', Path(upload.name).stem[:100] + '.dcm'
