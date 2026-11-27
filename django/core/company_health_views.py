from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from .master import _guard
from .master_console import companies
from .company_health import company_health

@login_required
def dashboard(request):
    _guard(request.user)
    query=request.GET.get('q','').strip()[:100]
    rows=companies().order_by('-created_at')
    if query: rows=rows.filter(name__icontains=query)
    page=Paginator(rows,25).get_page(request.GET.get('page'))
    return render(request,'master/company_health.html',{'rows':[company_health(t) for t in page],'page':page,'query':query})
