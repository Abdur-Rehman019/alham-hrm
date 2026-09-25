from django import forms


class ExcelUploadForm(forms.Form):
    file = forms.FileField(
        label='Excel file (.xlsx)',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.xlsx'})
    )