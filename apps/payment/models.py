from django.db import models
from django.conf import settings
from decimal import Decimal


class Payment(models.Model):
    """Модель платежа"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
    ]

    PAYMENT_METHOD_CHOICES = [
        ('stripe', 'Stripe'),
        ('paypal', 'PayPal'),
        ('manual', 'Manual'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    subscription = models.ForeignKey(
        'subscribe.Subscription',
        on_delete=models.CASCADE,
        related_name='payments',
        null=True,
        blank=True
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='EUR')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='stripe')
    
    # Stripe-специфичные поля
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_session_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    
    # Метаданные
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    # Временные метки
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'payments'
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['stripe_payment_intent_id']),
            models.Index(fields=['stripe_session_id']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Payment {self.id} - {self.user.username} - ${self.amount} ({self.status})"

    @property
    def is_successful(self):
        """Проверяет, успешен ли платеж"""
        return self.status == 'succeeded'

    @property
    def is_pending(self):
        """Проверяет, ожидает ли платеж обработки"""
        return self.status in ['pending', 'processing']

    @property
    def can_be_refunded(self):
        """Проверяет, можно ли вернуть платеж"""
        return self.status == 'succeeded' and self.payment_method == 'stripe'

    def mark_as_succeeded(self):
        """Помечает платеж как успешный"""
        from django.utils import timezone
        self.status = 'succeeded'
        self.processed_at = timezone.now()
        self.save()

    def mark_as_failed(self, reason=None):
        """Помечает платеж как неудачный"""
        from django.utils import timezone
        self.status = 'failed'
        self.processed_at = timezone.now()
        if reason:
            self.metadata['failure_reason'] = reason
        self.save()


class PaymentAttempt(models.Model):
    """Попытки платежа"""
    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name='attempts'
    )
    stripe_charge_id = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=50)
    error_message = models.TextField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payment_attempts'
        verbose_name = 'Payment Attempt'
        verbose_name_plural = 'Payment Attempts'
        ordering = ['-created_at']

    def __str__(self):
        return f"Attempt for Payment {self.payment.id} - {self.status}"
    

class Refund(models.Model):
    """Модель возврата средств"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name='refunds'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    stripe_refund_id = models.CharField(max_length=255, blank=True, null=True)
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_refunds'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'refunds'
        verbose_name = 'Refund'
        verbose_name_plural = 'Refunds'
        ordering = ['-created_at']

    def __str__(self):
        return f"Refund {self.id} - ${self.amount} for Payment {self.payment.id}"
    
    @property
    def is_partial(self):
        """Проверяет, является ли возврат частичным"""
        return self.amount < self.payment.amount

    def process_refund(self):
        """Обрабатывает возврат средств"""
        from django.utils import timezone
        self.status = 'succeeded'
        self.processed_at = timezone.now()
        self.save()


class WebhookEvent(models.Model):
    """События webhook от платежных систем"""
    PROVIDER_CHOICES = [
        ('stripe', 'Stripe'),
        ('paypal', 'PayPal'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
        ('ignored', 'Ignored'),
    ]

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    data = models.JSONField()
    processed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'webhook_events'
        verbose_name = 'Webhook Event'
        verbose_name_plural = 'Webhook Events'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['provider', 'event_type']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.provider} - {self.event_type} ({self.status})"

    def mark_as_processed(self):
        """Помечает событие как обработанное"""
        from django.utils import timezone
        self.status = 'processed'
        self.processed_at = timezone.now()
        self.save()

    def mark_as_failed(self, error_message):
        """Помечает событие как неудачно обработанное"""
        from django.utils import timezone
        self.status = 'failed'
        self.error_message = error_message
        self.processed_at = timezone.now()
        self.save()
    

