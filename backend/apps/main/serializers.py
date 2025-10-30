from rest_framework import serializers
from django.utils.text import slugify
from .models import Category, Post


class CategorySerializer(serializers.ModelSerializer):
    """Сериализатор для категорий"""
    posts_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'posts_count', 'created_at']
        read_only_fields = ['slug', 'created_at']

    def get_posts_count(self, obj):
        return obj.posts.filter(status='published').count()
    
    def create(self, validated_data):
        validated_data['slug'] = slugify(validated_data['name'])
        return super().create(validated_data)
    

class PostListSerializer(serializers.ModelSerializer):
    """Сериализатор для списка постов"""
    author = serializers.StringRelatedField()
    category = serializers.StringRelatedField()
    comments_count = serializers.ReadOnlyField()
    is_pinned = serializers.ReadOnlyField()
    pinned_info = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'title', 'slug', 'content', 'image', 'category',
            'author', 'status', 'created_at', 'updated_at',
            'views_count', 'comments_count', 'is_pinned', 'pinned_info'
        ]
        read_only_fields = ['slug', 'author', 'views_count']

    def get_pinned_info(self, obj):
        """Возвращает информацию о закреплении"""
        return obj.get_pinned_info()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Обрезаем контент для списка
        if len(data['content']) > 200:
            data['content'] = data['content'][:200] + '...'
        return data
    
class PostDetailSerializer(serializers.ModelSerializer):
    """Сериализатор для детального просмотра поста"""
    author_info = serializers.SerializerMethodField()
    category_info = serializers.SerializerMethodField()
    comments_count = serializers.ReadOnlyField()
    is_pinned = serializers.ReadOnlyField()
    pinned_info = serializers.SerializerMethodField()
    can_pin = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'title', 'slug', 'content', 'image', 'category',
            'category_info', 'author', 'author_info', 'status',
            'created_at', 'updated_at', 'views_count', 'comments_count',
            'is_pinned', 'pinned_info', 'can_pin'
        ]
        read_only_fields = ['slug', 'author', 'views_count']

    def get_author_info(self, obj):
        author = obj.author
        return {
            'id': author.id,
            'username': author.username,
            'full_name': author.full_name,
            'avatar': author.avatar.url if author.avatar else None
        }
    
    def get_category_info(self, obj):
        if obj.category:
            return {
                'id': obj.category.id,
                'name': obj.category.name,
                'slug': obj.category.slug,
            }
        return None
    
    def get_pinned_info(self, obj):
        return obj.get_pinned_info()
    
    def get_can_pin(self, obj):
        """Проверяет, может ли текущий пользователь закрпить пост"""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return obj.can_be_pinned_by(request.user)


class PostCreateUpdateSerializer(serializers.ModelSerializer):
    """Сериализатор для создания и обновления постов"""
    
    class Meta:
        model = Post
        fields = ['title', 'content', 'image', 'category', 'status']

    def create(self, validated_data):
        validated_data['author'] = self.context['request'].user
        validated_data['slug'] = slugify(validated_data['title'])
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if 'title' in validated_data:
            validated_data['slug'] = slugify(validated_data['title'])
        return super().update(instance, validated_data)
    