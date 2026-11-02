from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from .models import User
from common.permissions import has_global_scope

class ProfileSerializer(serializers.ModelSerializer):
    capabilities = serializers.SerializerMethodField()

    def get_capabilities(self, obj) -> dict[str, bool]:
        global_scope = has_global_scope(obj)
        return {'global_scope': global_scope, 'manage_branches': global_scope,
                'manage_users': obj.is_superuser or obj.role == 'super_admin',
                'sales_write': global_scope or obj.role in ('branch_manager', 'counsellor'),
                'manage_routing': global_scope or obj.role == 'branch_manager'}

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'role', 'branch', 'capabilities']
        read_only_fields = fields

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, max_length=1024, trim_whitespace=False)

class CSRFSerializer(serializers.Serializer):
    csrfToken = serializers.CharField()

class CSRFView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=CSRFSerializer)
    def get(self, request):
        return Response({'csrfToken': get_token(request)})

class LoginThrottle(SimpleRateThrottle):
    scope = 'login'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}

@method_decorator(csrf_protect, name='dispatch')
class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    @extend_schema(request=LoginSerializer, responses=ProfileSerializer)
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(request, **serializer.validated_data)
        if user is None:
            return Response({'detail': 'Invalid credentials.'}, status=status.HTTP_401_UNAUTHORIZED)
        login(request, user)
        return Response(ProfileSerializer(user).data)

class ProfileView(APIView):
    @extend_schema(responses=ProfileSerializer)
    def get(self, request):
        return Response(ProfileSerializer(request.user).data)

@method_decorator(csrf_protect, name='dispatch')
class LogoutView(APIView):
    # Signing out an already expired session is still a successful logout.
    # Explicit CSRF protection also covers anonymous requests.
    permission_classes = [AllowAny]

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)
