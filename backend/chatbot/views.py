from django.contrib.auth import authenticate
from rest_framework.response import Response
from rest_framework.generics import GenericAPIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import AllowAny
from .models import MyUser, Message
from .serializers import RegisterSerializer, LoginSerializer, PasswordResetRequestSerializer, PasswordResetConfirmSerializer
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import smart_bytes, force_str, DjangoUnicodeDecodeError
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.contrib.auth.password_validation import validate_password
from rest_framework.decorators import api_view,  permission_classes
from django.http import JsonResponse
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
import json
from .huggingface_service import query_huggingface  
from .serializers import (
    RegisterSerializer,
    LoginSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    MessageSerializer
)
from rest_framework.permissions import IsAuthenticated

# ------------------------ Views ------------------------

# Registration View
class RegisterView(GenericAPIView):
    queryset = MyUser.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response({
                'user_id': user.id,
                'email': user.email,
                'first_name': user.first_name,
            }, status=201)
        return Response(serializer.errors, status=400)


# Login View
class LoginView(GenericAPIView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']

            # Generate tokens using Simple JWT
            refresh = RefreshToken.for_user(user)
            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'user_id': user.id,
                'email': user.email,
                'first_name': user.first_name,
            })

        return Response(serializer.errors, status=400)


# Password Reset Request View
class PasswordResetRequestView(GenericAPIView):
    serializer_class = PasswordResetRequestSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            user = MyUser.objects.get(email=email)

            token_generator = PasswordResetTokenGenerator()
            token = token_generator.make_token(user)
            uidb64 = urlsafe_base64_encode(smart_bytes(user.id))

            reset_link = f"http://127.0.0.1:8000/api/password-reset-confirm/{uidb64}/{token}/"
            return Response({"reset_link": reset_link}, status=200)
        return Response(serializer.errors, status=400)


# Password Reset Confirm View
class PasswordResetConfirmView(GenericAPIView):
    serializer_class = PasswordResetConfirmSerializer
    permission_classes = [AllowAny]

    def post(self, request, uidb64, token, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Password reset successfully!"}, status=200)
        return Response(serializer.errors, status=400)


def home(request):
    return HttpResponse("Welcome to the Homepage!")


@csrf_exempt
def get_data(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user_input = data.get('message', '')

            if not user_input:
                return JsonResponse({'error': 'No message found in the request'}, status=400)

            # Context for the assistant
            system_context = """
            You are an advanced personal assistant designed to assist medical professionals with accurate, actionable health advice. When answering questions about health conditions such as headaches, provide detailed steps for relief, advice on when to seek medical help, and always prioritize safety and accuracy.

            Avoid guessing and misinformation: If the question is unclear or requires more details to provide an accurate response, ask follow-up questions.
            """

            # Query the Hugging Face API for a response
            bot_response = query_huggingface(user_input, system_context)

            # Save the message to the database if the user is authenticated
            if request.user.is_authenticated:
                Message.objects.create(user=request.user, message=user_input, response=bot_response)

            # Return the response as JSON
            return JsonResponse({'response': bot_response})

        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON input'}, status=400)

    return JsonResponse({'error': 'Invalid request method'}, status=400)


# Conversation-related Views

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_conversation(request):
    user = request.user
    conversation_id = request.data.get('conversation_id')
    title = request.data.get('title', 'Untitled Conversation')
    conversation_data = request.data.get('conversation', [])

    if conversation_id:
        # Update existing conversation
        try:
            conversation = Message.objects.get(id=conversation_id, user=user)
            conversation.title = title
            conversation.conversation = conversation_data
            conversation.save()
            return Response({'message': 'Conversation updated successfully'}, status=200)
        except Message.DoesNotExist:
            return Response({'error': 'Conversation not found'}, status=404)
    else:
        # Create new conversation
        conversation = Message.objects.create(user=user, title=title, conversation=conversation_data)
        return Response({
            'message': 'Conversation created successfully',
            'conversation_id': conversation.id
        }, status=201)


# Get all conversations for a user (list titles)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_conversations(request):
    user = request.user
    conversations = Message.objects.filter(user=user).order_by('-timestamp')
    serializer = MessageSerializer(conversations, many=True)
    return Response(serializer.data)


# Get a specific conversation by ID
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_conversation_detail(request, conversation_id):
    try:
        conversation = Message.objects.get(id=conversation_id, user=request.user)
        serializer = MessageSerializer(conversation)
        return Response(serializer.data)
    except Message.DoesNotExist:
        return Response({'error': 'Conversation not found'}, status=404)


# Update conversation title
@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_conversation_title(request, conversation_id):
    try:
        # Get the conversation by ID
        conversation = Message.objects.get(id=conversation_id, user=request.user)

        # Get the new title from the request data
        new_title = request.data.get('title', None)

        if not new_title:
            return Response({'error': 'Title is required.'}, status=400)

        # Update the title and save the conversation
        conversation.title = new_title
        conversation.save()

        return Response({'message': 'Title updated successfully.'}, status=200)

    except Message.DoesNotExist:
        return Response({'error': 'Conversation not found.'}, status=404)


# Get the latest conversation
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_latest_conversation(request):
    user = request.user
    try:
        latest_conversation = Message.objects.filter(user=user).latest('timestamp')
        serializer = MessageSerializer(latest_conversation)
        return Response(serializer.data, status=200)
    except Message.DoesNotExist:
        return Response({'detail': 'No conversation found'}, status=404)
    except Exception as e:
        return Response({'detail': str(e)}, status=500)


# Start a new conversation
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def start_new_conversation(request):
    user = request.user
    # Create a new conversation with an empty message list
    new_conversation = Message.objects.create(user=user, conversation=[], title="New Conversation")
    return Response({'conversation_id': new_conversation.id}, status=201)
