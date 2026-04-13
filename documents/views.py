from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import DocumentUser
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.serializers import ModelSerializer
import logging

logger = logging.getLogger(__name__)

class DocumentUserSerializer(ModelSerializer):
    # Serializer for DocumentUser model
    class Meta:
        model = DocumentUser
        fields = ['id', 'title', 'file', 'status', 'uploaded_at', 'metadata']
        read_only_fields = ['status', 'uploaded_at', 'metadata']


class DocumentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = DocumentUserSerializer
    
    def get_queryset(self):
        return DocumentUser.objects.filter(user=self.request.user)
    
    def create(self, request, *args, **kwargs):
        # Handle document upload
        file = request.FILES.get('file') or request.data.get('file')
        title = request.data.get('title', getattr(file, 'name', 'Untitled') if file else 'Untitled')
        
        if not file:
            logger.warning(f"Upload request missing file. FILES: {list(request.FILES.keys())}")
            return Response(
                {'error': 'No file provided in request'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Validate file type (PDF only)
            if not file.name.lower().endswith('.pdf'):
                return Response(
                    {'error': 'Only PDF files are supported'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Check file size (max 50MB)
            if file.size > 50 * 1024 * 1024:
                return Response(
                    {'error': 'File size must be less than 50MB'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Create document record immediately
            doc = DocumentUser.objects.create(
                user=request.user,
                title=title,
                file=file,
                status='PENDING'
            )
            logger.info(f"Document created: {doc.id} for user {request.user.id}")
            
            # Start processing in background thread
            import threading
            def process_document():
                try:
                    logger.info(f"Starting processing for document {doc.id}")
                    from rag.pipeline import ingest_document
                    
                    # Update to PROCESSING
                    doc.status = 'PROCESSING'
                    doc.save()
                    
                    # Process the document
                    ingest_document(doc.file.path, doc.id, doc.user.id)
                    
                    # Mark as completed
                    doc.status = 'COMPLETED'
                    doc.save()
                    logger.info(f"Document {doc.id} processing completed")
                except Exception as e:
                    logger.error(f"Error processing document {doc.id}: {str(e)}", exc_info=True)
                    doc.status = 'FAILED'
                    doc.metadata = {'error': str(e)}
                    doc.save()
            
            # Start thread in background
            thread = threading.Thread(target=process_document, daemon=True)
            thread.start()
            
            return Response({
                'id': doc.id,
                'title': doc.title,
                'status': 'PENDING',
                'message': 'Document uploaded successfully. Processing started in background.'
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error uploading document: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Upload failed: ' + str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
