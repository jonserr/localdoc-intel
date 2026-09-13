from django.urls import path

from .views import ChatHistoryView, ChatQueryView

urlpatterns = [
    path("chat/query/", ChatQueryView.as_view(), name="chat-query"),
    path("chat/history/", ChatHistoryView.as_view(), name="chat-history"),
]
