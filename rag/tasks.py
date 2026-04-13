from celery import shared_task
from documents.models import DocumentUser
import logging
import os

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def process_document_task(self, document_id):
    """
    Celery task to process uploaded documents asynchronously.
    Retries up to 3 times on failure.
    """
    doc = None
    try:
        # Fetch the document from DB
        doc = DocumentUser.objects.get(id=document_id)
        
        if not doc.file:
            raise FileNotFoundError(f"Document file not found for document {document_id}")
        
        # Check file exists
        if not os.path.exists(doc.file.path):
            raise FileNotFoundError(f"File path does not exist: {doc.file.path}")
        
        # Update status
        doc.status = 'PROCESSING'
        doc.save()
        logger.info(f"Starting to process document {document_id}: {doc.title}")

        # The actual RAG ingestion logic
        from rag.pipeline import ingest_document
        ingest_document(doc.file.path, doc.id, doc.user.id)

        # Update status to COMPLETED
        doc.status = 'COMPLETED'
        doc.metadata = {'processed_at': str(__import__('datetime').datetime.now())}
        doc.save()
        logger.info(f"Document {document_id} processed successfully")
        return f"Document {document_id} processed successfully."
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"Error processing document {document_id}: {str(e)}\n{error_trace}")
        
        # Update document status to FAILED
        if doc:
            doc.status = 'FAILED'
            doc.metadata = {'error': str(e), 'traceback': error_trace}
            doc.save()
        
        # Retry with exponential backoff
        try:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        except Exception as retry_error:
            logger.error(f"Max retries exceeded for document {document_id}: {str(retry_error)}")
            return f"Failed to process document {document_id} after retries: {str(e)}"
