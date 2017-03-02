import logging
logger = logging.getLogger(__name__)
import tarfile, tempfile, os, fnmatch

from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin

import django_rq

from researcher.forms import UploadArticlesForm, UploadSchemaForm
from researcher.forms import SendTasksForm
from data.load_data import load_article, load_schema
from data.parse_document import parse_article
from data.parse_schema import parse_schema
from data.legacy.parse_schema import parse_schema as old_parse_schema

from data.pybossa_api import create_remote_project
from data.pybossa_api import generate_highlight_tasks_worker
from data.pybossa_api import generate_quiz_tasks_worker
from data.pybossa_api import InvalidTaskType
from thresher.models import Article, Topic, UserProfile

class IndexView(TemplateView):
    template_name = 'researcher/index.html'

    def get(self, request):
        # We need 'request' in the context so use render
        return render(request, self.template_name)

@django_rq.job('default', timeout=60, result_ttl=24*3600)
def import_article(filename, owner_profile_id):
    owner_profile = UserProfile.objects.get(pk=owner_profile_id)
    with tarfile.open(filename) as tar:
        members = [ af for af in tar.getmembers()
                        if af.isfile() and fnmatch.fnmatch(af.name, "*.txt")]
        logger.info("articles found %d" % len(members))
        for member in members:
            article = tar.extractfile(member).read()
            load_article(parse_article(article, member.name), owner_profile)
    os.remove(filename)

@django_rq.job('default', timeout=60, result_ttl=24*3600)
def import_schema(filename, owner_profile_id):
    load_schema(old_parse_schema(filename))
    os.remove(filename)

class UploadArticlesView(PermissionRequiredMixin, View):
    form_class = UploadArticlesForm
    template_name = 'researcher/upload_article_form.html'
    login_url = reverse_lazy('admin:login')
    redirect_field_name = 'next'
    permission_required = u'thresher.add_article'

    def get(self, request):
        return render(
            request,
            self.template_name,
            {'form': self.form_class()}
        )

    def post(self, request):
        bound_form = self.form_class(request.POST, request.FILES)
        if bound_form.is_valid():
            f = request.FILES['article_archive_file']
            logger.info("Request to import article archive %s, length %d" % (f.name, f.size))
            with tempfile.NamedTemporaryFile(delete=False) as archive_file:
                for chunk in f.chunks():
                    archive_file.write(chunk)
                archive_file.flush()
                logger.info("Archive copied to temp file %s: tar file format: %s"
                            % (archive_file.name, tarfile.is_tarfile(archive_file.name)))
                # Async job must delete temp file when done
                import_article.delay(archive_file.name, request.user.userprofile.id)

            return redirect('/admin/thresher/article/')
        else:
            return render(
                request,
                self.template_name,
                {'form': bound_form}
            )

class UploadSchemaView(PermissionRequiredMixin, View):
    form_class = UploadSchemaForm
    template_name = 'researcher/upload_schema_form.html'
    login_url = reverse_lazy('admin:login')
    redirect_field_name = 'next'
    permission_required = (
        u'thresher.add_topic',
        u'thresher.add_question',
        u'thresher.add_answer',
    )

    def get(self, request):
        return render(
            request,
            self.template_name,
            {'form': self.form_class()}
        )

    def post(self, request):
        bound_form = self.form_class(request.POST, request.FILES)
        if bound_form.is_valid():
            f = request.FILES['schema_file']
            logger.info("Request to import schema %s, length %d" % (f.name, f.size))
            with tempfile.NamedTemporaryFile(delete=False) as schema_file:
                for chunk in f.chunks():
                    schema_file.write(chunk)
                schema_file.flush()
                logger.info("Schema copied to temp file %s" % schema_file.name)
                # Async job must delete temp file when done
                import_schema.delay(schema_file.name, request.user.userprofile.id)

            return redirect('/admin/thresher/topic/')
        else:
            return render(
                request,
                self.template_name,
                {'form': bound_form}
            )

class SendTasksView(PermissionRequiredMixin, View):
    form_class = SendTasksForm
    template_name = 'researcher/send_tasks.html'
    login_url = reverse_lazy('admin:login')
    redirect_field_name = 'next'
    # We are creating remotely, so real permission is via Pybossa API key.
    # Put some requirements on form access.
    permission_required = (
        u'thresher.add_project',
        u'thresher.change_project',
    )

    def get_task_generator(self, project):
        if project.task_type == "HLTR":
            return generate_highlight_tasks_worker.delay
        elif project.task_type == "QUIZ":
            return generate_quiz_tasks_worker.delay
        else:
            raise InvalidTaskType("Project task type must be 'HLTR' or 'QUIZ'")

    def get(self, request):
        return render(
            request,
            self.template_name,
            {'form': self.form_class(),
             'user': request.user
            }
        )

    def post(self, request):
        bound_form = self.form_class(request.POST)
        if request.user.is_authenticated and bound_form.is_valid():
            profile_id = request.user.userprofile.id
            article_ids = list(Article.objects.all().values_list('id', flat=True))
            topic_ids = list(Topic.objects.filter(parent=None)
                             .values_list('id', flat=True))
            project = bound_form.cleaned_data['project']
            project_id = project.id
            job = None
            if not project.pybossa_id:
                job = create_remote_project(request.user.userprofile, project)
            generator = self.get_task_generator(project)
            generator(profile_id=profile_id,
                      article_ids=article_ids,
                      topic_ids=topic_ids,
                      project_id=project_id,
                      depends_on = job)

            return redirect(reverse('rq_home'))
        else:
            return render(
                request,
                self.template_name,
                {'form': self.form_class(),
                 'user': request.user
                }
            )
