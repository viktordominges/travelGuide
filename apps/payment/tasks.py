from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import Payment, WebhookEvent


@shared_task
def cleanup_old_payments():
    """Очистка старых платежных записей"""
    cutoff_date = timezone.now() - timedelta(days=90)
    
    # Удаляем старые неудачные/отмененные платежи
    old_payments = Payment.objects.filter(
        created_at__lt=cutoff_date,
        status__in=['failed', 'cancelled']
    )
    
    deleted_payments, _ = old_payments.delete()
    
    return {'deleted_payments': deleted_payments}

@shared_task
def cleanup_old_webhook_events():
    """Очистка старых webhook событий"""
    cutoff_date = timezone.now() - timedelta(days=30)
    
    # Удаляем старые обработанные события
    old_events = WebhookEvent.objects.filter(
        created_at__lt=cutoff_date,
        status__in=['processed', 'ignored']
    )
    
    deleted_events, _ = old_events.delete()
    
    return {'deleted_webhook_events': deleted_events}

@shared_task
def retry_failed_webhook_events():
    """Повторная обработка неудачных webhook событий"""
    from .services import WebhookService
    
    # Находим события, которые не удалось обработать в последние 24 часа
    retry_cutoff = timezone.now() - timedelta(hours=24)
    
    failed_events = WebhookEvent.objects.filter(
        status='failed',
        created_at__gte=retry_cutoff
    )[:50]  # Ограничиваем количество для повторной обработки
    
    processed_count = 0
    
    for event in failed_events:
        success = WebhookService.process_stripe_webhook(event.data)
        if success:
            event.mark_as_processed()
            processed_count += 1
    
    return {'reprocessed_events': processed_count}