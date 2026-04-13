import os
import logging
import datetime

logger = logging.getLogger(__name__)

# FAISS vector store path
FAISS_PATH = os.path.join(os.path.dirname(__file__), 'faiss_index')

def get_embeddings():
    # Returns local HuggingFace embeddings to avoid OpenAI quota/cost issues.
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        logger.info("Initializing HuggingFace embeddings (all-MiniLM-L6-v2)...")
        # Fallback to local model that works perfectly for interviews
        return HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    except Exception as e:
        logger.error(f"Failed to load local embeddings: {e}")
        raise

def get_llm(model_type="gpt-4"):
    # Returns the requested LLM. Choices: 'gpt-4', 'mistral'
    if model_type == "mistral":
        from langchain_huggingface import HuggingFaceEndpoint, ChatHuggingFace
        repo_id = "mistralai/Mistral-7B-Instruct-v0.2"
        llm = HuggingFaceEndpoint(
            repo_id=repo_id,
            huggingfacehub_api_token=os.getenv("HUGGINGFACEHUB_API_TOKEN"),
            temperature=0.5,
        )
        return ChatHuggingFace(llm=llm)
    else:
        from langchain_openai import ChatOpenAI
        # Default to GPT-4o
        return ChatOpenAI(
            model_name="gpt-4o", 
            openai_api_key=os.getenv("OPENAI_API_KEY")
        )

def ingest_document(file_path, doc_id, user_id):
    # Processes a PDF and stores embeddings in FAISS.
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_community.vectorstores import FAISS
    
    try:
        logger.info(f"Starting document ingestion for doc_id={doc_id}")
        
        loader = PyPDFLoader(file_path)
        documents = loader.load()
        logger.info(f"Loaded {len(documents)} pages from PDF")

        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        texts = text_splitter.split_documents(documents)
        logger.info(f"Split into {len(texts)} chunks")

        # Add metadata to track user and document
        for text in texts:
            text.metadata['document_id'] = str(doc_id)
            text.metadata['user_id'] = str(user_id)

        embeddings = get_embeddings()

        # Load or create FAISS index
        if os.path.exists(FAISS_PATH) and os.path.exists(os.path.join(FAISS_PATH, "index.faiss")):
            logger.info("Loading existing FAISS index")
            vector_store = FAISS.load_local(FAISS_PATH, embeddings, allow_dangerous_deserialization=True)
            vector_store.add_documents(texts)
        else:
            logger.info("Creating new FAISS index")
            vector_store = FAISS.from_documents(texts, embeddings)
        
        # Ensure directory exists
        os.makedirs(FAISS_PATH, exist_ok=True)
        vector_store.save_local(FAISS_PATH)
        logger.info(f"FAISS index saved to {FAISS_PATH}")
        
        return True
    except Exception as e:
        logger.error(f"Error ingesting document: {str(e)}", exc_info=True)
        raise

def ask_question(question, user_id, document_id=None, model_type="gpt-4"):
    # Query the RAG pipeline using FAISS with metadata filtering.
    try:
        logger.info(f"Processing question for user {user_id}")
        
        embeddings = get_embeddings()

        # Check if FAISS index exists
        if not os.path.exists(FAISS_PATH) or not os.path.exists(os.path.join(FAISS_PATH, "index.faiss")):
            logger.warning("FAISS index not found")
            return "I am sorry, but your document has not been fully processed yet. Please wait a moment."
        
        # Load FAISS index
        from langchain_community.vectorstores import FAISS
        vector_store = FAISS.load_local(FAISS_PATH, embeddings, allow_dangerous_deserialization=True)

        # Custom retriever with metadata filtering
        class FilteredRetriever:
            def __init__(self, vs, user_id, doc_id=None):
                self.vs = vs
                self.user_id = str(user_id)
                self.doc_id = str(doc_id) if doc_id else None
            
            def get_relevant_documents(self, query):
                raw_results = self.vs.similarity_search(query, k=10)
                filtered = []
                for doc in raw_results:
                    if doc.metadata.get('user_id') != self.user_id:
                        continue
                    if self.doc_id and doc.metadata.get('document_id') != self.doc_id:
                        continue
                    filtered.append(doc)
                return filtered[:5]
            
            async def aget_relevant_documents(self, query):
                return self.get_relevant_documents(query)

        from langchain_core.prompts import ChatPromptTemplate
        try:
            from langchain.chains import create_retrieval_chain
            from langchain.chains.combine_documents import create_stuff_documents_chain
        except (ImportError, ModuleNotFoundError):
            from langchain_classic.chains import create_retrieval_chain
            from langchain_classic.chains.combine_documents import create_stuff_documents_chain

        retriever = FilteredRetriever(vector_store, user_id, document_id)
        llm = get_llm(model_type)

        system_prompt = (
            "You are an assistant for research tasks. "
            "Use the following pieces of retrieved context to answer the question. "
            "If you don't know the answer, say that you don't know. "
            "Use three sentences maximum and keep the answer concise.\n\n{context}"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}"),
        ])

        question_answer_chain = create_stuff_documents_chain(llm, prompt)
        rag_chain = create_retrieval_chain(retriever, question_answer_chain)

        response = rag_chain.invoke({"input": question})
        return response["answer"]
    
    except Exception as e:
        logger.error(f"Error in ask_question: {str(e)}", exc_info=True)
        return f"An error occurred while processing your question: {str(e)}"
