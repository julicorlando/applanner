from django.contrib import admin
from .models import (
    CashSession, FinancialCategory, FinancialTransaction, Product,
    ProductStockMovement, ProfessionalCommission, Sale, SaleItem,
)


@admin.register(FinancialCategory)
class FinancialCategoryAdmin(admin.ModelAdmin):
    list_display=("name","tenant","type","active")
    list_filter=("type","active","tenant")


@admin.register(FinancialTransaction)
class FinancialTransactionAdmin(admin.ModelAdmin):
    list_display=("description","tenant","type","amount","status","due_at","paid_at")
    list_filter=("type","status","tenant")
    search_fields=("description","idempotency_key")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display=("name","tenant","sku","sale_price","stock","active")
    list_filter=("active","tenant")
    search_fields=("name","sku","code")


class SaleItemInline(admin.TabularInline):
    model=SaleItem
    extra=0


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display=("id","tenant","customer","professional","total","payment_method","status","created_at")
    list_filter=("status","payment_method","tenant")
    inlines=[SaleItemInline]


admin.site.register(ProductStockMovement)
admin.site.register(CashSession)
admin.site.register(ProfessionalCommission)
