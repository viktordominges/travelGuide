from rest_framework import generics, permissions, filters
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404

from .models import Comment
from .serializers import (
    CommentSerializer,
    CommentCreateSerializer,
    CommentUpdateSerializer,
    CommentDetailSerializer
)
from .permissions import IsAuthorOrReadOnly
from apps.main.models import Post


class CommentListCreateView(generics.ListCreateAPIView):
    """Список и создание комментариев"""
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['post', 'author', 'parent']
    search_fields = ['content']
    ordering_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']

    def get_queryset(self):
        return Comment.objects.filter(is_active=True).select_related(
            'author', 'post', 'parent'
        )
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return CommentCreateSerializer
        return CommentSerializer
    

class CommentDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Детальный просмотр, обновление и удаление комментария"""
    queryset = Comment.objects.filter(is_active=True).select_related('author', 'post')
    serializer_class = CommentDetailSerializer
    permission_classes = [IsAuthorOrReadOnly]

    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return CommentUpdateSerializer
        return CommentDetailSerializer

    def perform_destroy(self, instance):
        # Мягкое удаление - помечаем как неактивный
        instance.is_active = False
        instance.save()


class MyCommentsView(generics.ListAPIView):
    """Список комментариев текущего пользователя"""
    serializer_class = CommentSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['post', 'parent', 'is_active']
    search_fields = ['content']
    ordering_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']

    def get_queryset(self):
        return Comment.objects.filter(author=self.request.user).select_related(
            'post', 'parent'
        )
    
@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def post_comments(request, post_id):
    """Получить комментарий к определенному посту"""
    post = get_object_or_404(Post, id=post_id, status='published')

    # Получаем только основные комментарии
    comments = Comment.objects.filter(
        post=post,
        parent=None,
        is_active=True
    ).select_related('author').prefetch_related(
        'replies__author'
    ).order_by('-created_at')

    serializer = CommentDetailSerializer(comments, many=True, context={'request': request})
    return Response({
        'post': {
            'id': post.id,
            'title': post.title,
            'slug': post.slug
        },
        'comments': serializer.data,
        'comments_count': post.comments.filter(is_active=True).count()
    })

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def comment_replies(request, comment_id):
    """Получить ответы на комментарий"""
    parent_comment = get_object_or_404(Comment, id=comment_id, is_active=True)
    
    replies = Comment.objects.filter(
        parent=parent_comment,
        is_active=True
    ).select_related('author').order_by('created_at')
    
    serializer = CommentSerializer(replies, many=True, context={'request': request})
    return Response({
        'parent_comment': CommentSerializer(parent_comment, context={'request': request}).data,
        'replies': serializer.data,
        'replies_count': replies.count()
    })
    
