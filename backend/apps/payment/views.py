import stripe
import json
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils.decorators import method_decorator
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db import transaction

from .models import Payment, PaymentAttempt, Refund, WebhookEvent
from .serializers import (
    PaymentSerializer,
    PaymentCreateSerializer,
    PaymentAttemptSerializer,
    RefundSerializer,
    RefundCreateSerializer,
    StripeCheckoutSessionSerializer,
    PaymentStatusSerializer
)
from .services import StripeService, PaymentService, WebhookService
from apps.subscribe.models import SubscriptionPlan


class PaymentListView(generics.ListAPIView):
    """Список платежей пользователя"""
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Возвращает платежи текущего пользователя"""
        return Payment.objects.filter(
            user=self.request.user
        ).select_related('subscription', 'subscription__plan').order_by('-created_at')


class PaymentDetailView(generics.RetrieveAPIView):
    """Детальная информация о платеже"""
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Возвращает платежи текущего пользователя"""
        return Payment.objects.filter(
            user=self.request.user
        ).select_related('subscription', 'subscription__plan')
    
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_checkout_session(request):
    """Создает Stripe Checkout сессию для оплаты подписки"""
    serializer = PaymentCreateSerializer(data=request.data, context={'request': request})
    
    if serializer.is_valid():
        try:
            with transaction.atomic():
                plan_id = serializer.validated_data['subscription_plan_id']
                plan = get_object_or_404(SubscriptionPlan, id=plan_id, is_active=True)
                
                # Создаем платеж и подписку
                payment, subscription = PaymentService.create_subscription_payment(
                    request.user, plan
                )
                
                # Получаем URLs из запроса
                success_url = serializer.validated_data.get(
                    'success_url', 
                    f"{settings.FRONTEND_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}"
                )
                cancel_url = serializer.validated_data.get(
                    'cancel_url', 
                    f"{settings.FRONTEND_URL}/payment/cancel"
                )
                
                # Создаем Stripe сессию
                session_data = StripeService.create_checkout_session(
                    payment, success_url, cancel_url
                )
                
                if session_data:
                    response_serializer = StripeCheckoutSessionSerializer(session_data)
                    return Response(response_serializer.data, status=status.HTTP_201_CREATED)
                else:
                    return Response({
                        'error': 'Failed to create checkout session'
                    }, status=status.HTTP_400_BAD_REQUEST)
                    
        except Exception as e:
            return Response({
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def payment_status(request, payment_id):
    """Проверяет статус платежа"""
    try:
        payment = get_object_or_404(
            Payment, 
            id=payment_id, 
            user=request.user
        )
        
        # Если есть session_id, проверяем статус в Stripe
        if payment.stripe_session_id and payment.status in ['pending', 'processing']:
            session_info = StripeService.retrieve_session(payment.stripe_session_id)
            
            if session_info:
                if session_info['status'] == 'complete':
                    PaymentService.process_successful_payment(payment)
                elif session_info['status'] == 'failed':
                    PaymentService.process_failed_payment(payment, "Session failed")
        
        response_data = {
            'payment_id': payment.id,
            'status': payment.status,
            'message': f'Payment is {payment.status}',
            'subscription_activated': False
        }
        
        if payment.is_successful and payment.subscription:
            response_data['subscription_activated'] = payment.subscription.is_active
            response_data['message'] = 'Payment successful and subscription activated'
        
        serializer = PaymentStatusSerializer(response_data)
        return Response(serializer.data)
        
    except Payment.DoesNotExist:
        return Response({
            'error': 'Payment not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def cancel_payment(request, payment_id):
    """Отменяет платеж"""
    try:
        payment = get_object_or_404(
            Payment, 
            id=payment_id, 
            user=request.user
        )
        
        if not payment.is_pending:
            return Response({
                'error': 'Can only cancel pending payments'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        payment.status = 'cancelled'
        payment.save()
        
        # Отменяем подписку
        if payment.subscription:
            payment.subscription.cancel()
        
        return Response({
            'message': 'Payment cancelled successfully'
        })
        
    except Payment.DoesNotExist:
        return Response({
            'error': 'Payment not found'
        }, status=status.HTTP_404_NOT_FOUND)
    

class RefundListView(generics.ListAPIView):
    """Список возвратов для администраторов"""
    serializer_class = RefundSerializer
    permission_classes = [permissions.IsAdminUser]
    
    def get_queryset(self):
        return Refund.objects.all().select_related(
            'payment', 'payment__user', 'created_by'
        ).order_by('-created_at')


class RefundDetailView(generics.RetrieveAPIView):
    """Детальная информация о возврате"""
    serializer_class = RefundSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset = Refund.objects.all().select_related(
        'payment', 'payment__user', 'created_by'
    )

@api_view(['POST'])
@permission_classes([permissions.IsAdminUser])
def create_refund(request, payment_id):
    """Создает возврат для платежа"""
    try:
        payment = get_object_or_404(Payment, id=payment_id)
        
        if not payment.can_be_refunded:
            return Response({
                'error': 'This payment cannot be refunded'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        serializer = RefundCreateSerializer(
            data=request.data,
            context={'payment_id': payment_id}
        )
        
        if serializer.is_valid():
            with transaction.atomic():
                # Создаем возврат
                refund = serializer.save(
                    payment=payment,
                    created_by=request.user
                )
                
                # Обрабатываем возврат через Stripe
                success = StripeService.refund_payment(
                    payment, 
                    refund.amount, 
                    refund.reason
                )
                
                if success:
                    refund.process_refund()
                    
                    # Если это полный возврат, отменяем подписку
                    if refund.amount == payment.amount and payment.subscription:
                        PaymentService.cancel_subscription(payment.subscription)
                    
                    response_serializer = RefundSerializer(refund)
                    return Response(response_serializer.data, status=status.HTTP_201_CREATED)
                else:
                    refund.status = 'failed'
                    refund.save()
                    return Response({
                        'error': 'Failed to process refund'
                    }, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
    except Payment.DoesNotExist:
        return Response({
            'error': 'Payment not found'
        }, status=status.HTTP_404_NOT_FOUND)
    
@csrf_exempt
@require_POST
def stripe_webhook(request):
    """Webhook endpoint для Stripe"""
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    
    try:
        # Верифицируем webhook
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        # Неверный payload
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        # Неверная подпись
        return HttpResponse(status=400)
    
    # Обрабатываем событие
    success = WebhookService.process_stripe_webhook(event)
    
    if success:
        return HttpResponse(status=200)
    else:
        return HttpResponse(status=400)
    
@api_view(['GET'])
@permission_classes([permissions.IsAdminUser])
def payment_analytics(request):
    """Аналитика по платежам для администраторов"""
    from django.db.models import Count, Sum, Avg
    from django.utils import timezone
    from datetime import timedelta
    
    # Общая статистика
    total_payments = Payment.objects.count()
    successful_payments = Payment.objects.filter(status='succeeded').count()
    total_revenue = Payment.objects.filter(
        status='succeeded'
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    # Статистика за последний месяц
    last_month = timezone.now() - timedelta(days=30)
    monthly_payments = Payment.objects.filter(
        created_at__gte=last_month,
        status='succeeded'
    )
    monthly_revenue = monthly_payments.aggregate(
        total=Sum('amount')
    )['total'] or 0
    monthly_count = monthly_payments.count()
    
    # Средний чек
    avg_payment = Payment.objects.filter(
        status='succeeded'
    ).aggregate(avg=Avg('amount'))['avg'] or 0
    
    # Статистика по подпискам
    active_subscriptions = Payment.objects.filter(
        status='succeeded',
        subscription__status='active'
    ).count()
    
    return Response({
        'total_payments': total_payments,
        'successful_payments': successful_payments,
        'success_rate': (successful_payments / total_payments * 100) if total_payments > 0 else 0,
        'total_revenue': float(total_revenue),
        'monthly_revenue': float(monthly_revenue),
        'monthly_payments': monthly_count,
        'average_payment': float(avg_payment),
        'active_subscriptions': active_subscriptions,
        'period': {
            'from': last_month.isoformat(),
            'to': timezone.now().isoformat()
        }
    })

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def user_payment_history(request):
    """История платежей пользователя"""
    payments = Payment.objects.filter(
        user=request.user
    ).select_related('subscription', 'subscription__plan').order_by('-created_at')
    
    serializer = PaymentSerializer(payments, many=True)
    return Response({
        'count': payments.count(),
        'results': serializer.data
    })

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def retry_payment(request, payment_id):
    """Повторная попытка оплаты"""
    try:
        payment = get_object_or_404(
            Payment, 
            id=payment_id, 
            user=request.user,
            status='failed'
        )
        
        # Создаем новую сессию для повторной оплаты
        success_url = request.data.get(
            'success_url', 
            f"{settings.FRONTEND_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}"
        )
        cancel_url = request.data.get(
            'cancel_url', 
            f"{settings.FRONTEND_URL}/payment/cancel"
        )
        
        session_data = StripeService.create_checkout_session(
            payment, success_url, cancel_url
        )
        
        if session_data:
            # Обновляем статус платежа
            payment.status = 'processing'
            payment.save()
            
            response_serializer = StripeCheckoutSessionSerializer(session_data)
            return Response(response_serializer.data)
        else:
            return Response({
                'error': 'Failed to create checkout session'
            }, status=status.HTTP_400_BAD_REQUEST)
            
    except Payment.DoesNotExist:
        return Response({
            'error': 'Payment not found or cannot be retried'
        }, status=status.HTTP_404_NOT_FOUND)

