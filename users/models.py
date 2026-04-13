from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    # Overriding abstract user if necessary. Additional fields can be added here.
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.username
