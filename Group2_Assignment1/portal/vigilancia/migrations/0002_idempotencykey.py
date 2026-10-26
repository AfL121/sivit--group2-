from django.db import migrations, models


class Migration(migrations.Migration):
    """Tabela das chaves de idempotência (modelo IdempotencyKey).

    Estava em models.py mas não em 0001: só existia porque o arranque.sh
    corria makemigrations dentro do contentor. Agora está no Git.
    """

    dependencies = [
        ('vigilancia', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='IdempotencyKey',
            fields=[
                ('key', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('response', models.JSONField()),
                ('created', models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]