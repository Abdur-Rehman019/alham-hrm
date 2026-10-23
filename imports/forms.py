from django import forms
from django.core.validators import FileExtensionValidator

MAX_UPLOAD_MB = 5


class ExcelUploadForm(forms.Form):
    file = forms.FileField(
        label='Excel file (.xlsx)',
        validators=[FileExtensionValidator(['xlsx'])],
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.xlsx'})
    )

    def clean_file(self):
        uploaded = self.cleaned_data['file']
        if uploaded.size > MAX_UPLOAD_MB * 1024 * 1024:
            raise forms.ValidationError(f'The file is larger than {MAX_UPLOAD_MB} MB. Split it into smaller files.')
        # .xlsx files are zip archives; anything else is not a real Excel workbook.
        head = uploaded.read(4)
        uploaded.seek(0)
        if head != b'PK\x03\x04':
            raise forms.ValidationError('This is not a valid .xlsx Excel file.')
        return uploaded
