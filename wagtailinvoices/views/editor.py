from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.shortcuts import redirect, render, get_object_or_404
from django.utils.translation import ugettext_lazy as _
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

# TODO Swap with django.utils.lru_cache.lru_cache at Django 1.7
from django.utils.functional import memoize

from wagtail.wagtailadmin.edit_handlers import (
    ObjectList, extract_panel_definitions_from_model_class, get_form_for_model)
from wagtail.wagtailcore.models import Page

from ..models import get_invoiceindex_content_types


def get_invoice_edit_handler(Invoice):
    panels = extract_panel_definitions_from_model_class(
        Invoice, exclude=['invoiceindex'])
    EditHandler = ObjectList(panels).bind_to_model(Invoice)
    return EditHandler
get_invoice_edit_handler = memoize(get_invoice_edit_handler, {}, 1)


def get_invoice_form(Invoice, EditHandler):
    return get_form_for_model(
        Invoice,
        formsets=EditHandler.required_formsets(),
        widgets=EditHandler.widget_overrides(),
        exclude=['invoiceindex'])
get_invoice_form = memoize(get_invoice_form, {}, 2)


# Convert HTML URIs to absolute system paths so xhtml2pdf can access those resources
def link_callback(uri, rel):
    # use short variable names
    sUrl = settings.STATIC_URL      # Typically /static/
    sRoot = settings.STATIC_ROOT    # Typically /home/userX/project_static/
    mUrl = settings.MEDIA_URL       # Typically /static/media/
    mRoot = settings.MEDIA_ROOT     # Typically /home/userX/project_static/media/

    # convert URIs to absolute system paths
    if uri.startswith(mUrl):
        path = os.path.join(mRoot, uri.replace(mUrl, ""))
    elif uri.startswith(sUrl):
        path = os.path.join(sRoot, uri.replace(sUrl, ""))

    # make sure that file exists
    if not os.path.isfile(path):
            raise Exception(
                    'media URI must start with %s or %s' % \
                    (sUrl, mUrl))
    return path

def generate_pdf(request, type):
    # Set variables
    id = invoice.id
    # Prepare context
    data = {}
    data['today'] = datetime.date.today()
    data['farmer'] = 'Old MacDonald'
    data['animals'] = [('Cow', 'Moo'), ('Goat', 'Baa'), ('Pig', 'Oink')]

    # Render html content through html template with context
    template = get_template('invoices/invoice_pdf.html')
    html  = template.render(Context(data))

    # Write PDF to file
    file = open(os.join(settings.MEDIA_ROOT, 'Invoice #' + id + '.pdf'), "w+b")
    pisaStatus = pisa.CreatePDF(html, dest=file,
            link_callback = link_callback)

    # Return PDF document through a Django HTTP response
    file.seek(0)
    pdf = file.read()
    file.close()            # Don't forget to close the file handle
    return HttpResponse(pdf, mimetype='application/pdf')

def send_invoice(request, invoice):
    # Set Variables
    email = invoice.client_email
    name = invoice.client_full_name
    booking_details = invoice.client_booking_form
    def get_total(service_items):
        amount = 0
        for i in service_items:
            amount = amount + i.amount
        return amount
    total = get_total(invoice.service_items.all()) 
    gst = total / 11
    link = request.build_absolute_uri(invoice.url())
    id = invoice.id
    ph_number = invoice.client_phone_number
    adminmessage = render_to_string('emails/admin_invoice_message.txt', {
        'name': name,
        'ph_number': ph_number,
        'email': email,
        'booking_details': booking_details,
        'total': total,
        'gst': gst,
        'link': link,
        'invoice': invoice,
    })
    # Email to business owner
    admin_email = EmailMessage('Invoice #' + str(id), adminmessage, "admin@tasmanianexclusivetours.com.au",
        ['admin@tasmanianexclusivetours.com.au'])
    admin_email.content_subtype = "html"
    admin_email.send()
    # Customer Email
    invoicemessage = render_to_string('emails/invoice_message.txt', {
        'name': name,
        'booking_details': booking_details,
        'total': total,
        'gst': gst,
        'link': link,
        'invoice': invoice,
    })
    customer_email = EmailMessage('Invoice #' + str(id), invoicemessage, "admin@tasmanianexclusivetours.com.au",
                 [email])
    customer_email.content_subtype = "html"
    customer_email.send()

@permission_required('wagtailadmin.access_admin')  # further permissions are enforced within the view
def create(request, pk):
    invoiceindex = get_object_or_404(Page, pk=pk, content_type__in=get_invoiceindex_content_types()).specific
    Invoice = invoiceindex.get_invoice_model()

    invoice = Invoice()
    EditHandler = get_invoice_edit_handler(Invoice)
    EditForm = get_invoice_form(Invoice, EditHandler)  #LOOK

    if request.method == 'POST':
        form = EditForm(request.POST, request.FILES)

        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.invoiceindex = invoiceindex
            invoice.save()
            send_invoice(request, invoice)

            messages.success(request, _('The invoice "{0!s}" has been added').format(invoice))
            return redirect('wagtailinvoices_index', pk=invoiceindex.pk)
        else:
            messages.error(request, _('The invoice could not be created due to validation errors'))
            edit_handler = EditHandler(instance=invoice, form=form)
    else:
        form = EditForm(instance=invoice)
        edit_handler = EditHandler(instance=invoice, form=form)

    return render(request, 'wagtailinvoices/create.html', {
        'invoiceindex': invoiceindex,
        'form': form,
        'edit_handler': edit_handler,
    })


@permission_required('wagtailadmin.access_admin')  # further permissions are enforced within the view
def edit(request, pk, invoice_pk):
    invoiceindex = get_object_or_404(Page, pk=pk, content_type__in=get_invoiceindex_content_types()).specific
    Invoice = invoiceindex.get_invoice_model()
    invoice = get_object_or_404(Invoice, invoiceindex=invoiceindex, pk=invoice_pk)
    send_button_name = 'send_invoice'
    EditHandler = get_invoice_edit_handler(Invoice)
    EditForm = get_invoice_form(Invoice, EditHandler)

    if request.method == 'POST':
        form = EditForm(request.POST, request.FILES, instance=invoice)

        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.save()

            if send_button_name in request.POST:
                send_invoice(request, invoice)

            messages.success(request, _('The invoice "{0!s}" has been updated').format(invoice))
            return redirect('wagtailinvoices_index', pk=invoiceindex.pk)
        else:
            messages.error(request, _('The invoice could not be updated due to validation errors'))
            edit_handler = EditHandler(instance=invoice, form=form)
    else:
        form = EditForm(instance=invoice)
        edit_handler = EditHandler(instance=invoice, form=form)

    return render(request, 'wagtailinvoices/edit.html', {
        'invoiceindex': invoiceindex,
        'invoice': invoice,
        'send_button_name': send_button_name,
        'form': form,
        'edit_handler': edit_handler,
    })


@permission_required('wagtailadmin.access_admin')  # further permissions are enforced within the view
def delete(request, pk, invoice_pk):
    invoiceindex = get_object_or_404(Page, pk=pk, content_type__in=get_invoiceindex_content_types()).specific
    Invoice = invoiceindex.get_invoice_model()
    invoice = get_object_or_404(Invoice, invoiceindex=invoiceindex, pk=invoice_pk)

    if request.method == 'POST':
        invoice.delete()
        return redirect('wagtailinvoices_index', pk=pk)

    return render(request, 'wagtailinvoices/delete.html', {
        'invoiceindex': invoiceindex,
        'invoice': invoice,
    })