"""
management/commands/create_admin.py

Usage:
    python manage.py create_admin --username admin --password yourpassword

Place this file at:
    <your_app>/management/commands/create_admin.py

Make sure the management/ and management/commands/ folders each have an empty __init__.py
"""
from django.core.management.base import BaseCommand
from core.models import SystemUser   # ← change 'academy' to your actual app name


class Command(BaseCommand):
    help = 'Create the first admin user for Sports Academy'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, default='admin')
        parser.add_argument('--password', type=str, default='admin123')
        parser.add_argument('--name',     type=str, default='Super Admin')
        parser.add_argument('--email',    type=str, default='')

    def handle(self, *args, **options):
        username = options['username']
        password = options['password']

        if SystemUser.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f'User "{username}" already exists.'))
            return

        user = SystemUser(
            username=username,
            role='admin',
            full_name=options['name'],
            email=options['email'],
            is_active=True,
        )
        user.set_password(password)   # ← PBKDF2 encrypted
        user.save()

        self.stdout.write(self.style.SUCCESS(
            f'✓ Admin user "{username}" created successfully!\n'
            f'  Login at: /login/\n'
            f'  Password: {password}\n'
            f'  ⚠ Change your password after first login!'
        ))
