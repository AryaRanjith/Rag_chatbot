from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from documents.models import DocumentUser
from .models import ChatMessage
from rest_framework.serializers import ModelSerializer
import logging

logger = logging.getLogger(__name__)


class ChatAskView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        question = request.data.get('question')
        document_id = request.data.get('document_id', None)
        model_type = request.data.get('model_type', 'gpt-4')  # Default to gpt-4

        if not question or not question.strip():
            return Response(
                {'error': 'Question is required and cannot be empty'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate document exists and belongs to user if specified
        if document_id:
            try:
                doc = DocumentUser.objects.get(id=document_id, user=request.user)
                if doc.status != 'COMPLETED':
                    return Response(
                        {'error': f'Document is still {doc.status.lower()}. Please wait for processing to complete.'}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
                logger.info(f"User {request.user.id} querying document {document_id}")
            except DocumentUser.DoesNotExist:
                return Response(
                    {'error': 'Document not found or does not belong to you'}, 
                    status=status.HTTP_404_NOT_FOUND
                )

        # Pass to LangChain RAG pipeline
        try:
            from rag.pipeline import ask_question
            
            logger.info(f"Processing question: {question[:100]}... for user {request.user.id}")
            answer = ask_question(
                question, 
                user_id=request.user.id, 
                document_id=document_id,
                model_type=model_type
            )
            
            logger.info(f"Successfully generated answer for user {request.user.id}")
            
            # Save to history if document specified
            if document_id:
                ChatMessage.objects.create(
                    user=request.user,
                    document=doc,
                    question=question,
                    answer=answer
                )
            
            return Response({'answer': answer, 'status': 'success'})

        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"Error processing question for user {request.user.id}: {str(e)}\n{error_trace}")
            return Response(
                {'error': f'Failed to process your question: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class ChatMessageSerializer(ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ['id', 'question', 'answer', 'created_at']

class ChatHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, document_id):
        # Retrieve chat history for a specific document
        try:
            # Verify document exists and belongs to user
            doc = DocumentUser.objects.get(id=document_id, user=request.user)
            messages = ChatMessage.objects.filter(document=doc).order_by('created_at')
            serializer = ChatMessageSerializer(messages, many=True)
            return Response(serializer.data)
        except DocumentUser.DoesNotExist:
            return Response({'error': 'Document not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error fetching history: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
