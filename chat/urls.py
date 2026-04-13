from django.urls import path
from .views import ChatAskView, ChatHistoryView

urlpatterns = [
    path('ask/', ChatAskView.as_view(), name='chat_ask'),
    path('history/<int:document_id>/', ChatHistoryView.as_view(), name='chat_history'),
]
