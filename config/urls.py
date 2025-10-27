from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/auth/', include('apps.accounts.urls')),
    path('api/v1/posts/', include('apps.main.urls')),
    # path('api/v1/comments/', include('apps.comments.urls')),
    # path('api/v1/subscribe/', include('apps.subscribe.urls')),
    # path('api/v1/payment/', include('apps.payment.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
