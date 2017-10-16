# -*- coding: utf-8 -*-
# Generated by Django 1.11.2 on 2017-10-16 04:22
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('thresher', '0013_auto_20170930_2255'),
    ]

    operations = [
        migrations.AlterField(
            model_name='question',
            name='question_type',
            field=models.CharField(choices=[(b'RADIO', b'Radio buttons'), (b'CHECKBOX', b'Checkboxes'), (b'SELECT_SUBTOPIC', b'Subtopic checkboxes'), (b'TEXT', b'Text'), (b'DATE', b'Date'), (b'TIME', b'Time')], max_length=16),
        ),
    ]
