from django.shortcuts import render, redirect, get_object_or_404, reverse
from django.views import generic
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse

from .models import Snapshot


class IndexView(generic.ListView):
    template_name = 'morocco/snapshots.html'
    context_object_name = 'data'

    def get_queryset(self):
        """Return the last five published questions."""
        return Snapshot.objects.filter(ignore=False).order_by('-commit_date')


class UpdateSnapshot(generic.View):
    def post(self, request, sha):
        from .operation import ignore_snapshot, rebuild_snapshot, refresh_snapshot
        action = request.POST.get('action')
        if action == 'refresh':
            refresh_snapshot(sha)
        elif action == 'rebuild':
            rebuild_snapshot(sha, request)
        elif action == 'ignore':
            ignore_snapshot(sha)
        else:
            return 'Unknown action {}'.format(action or 'None'), 400

        return redirect('morocco:snapshot', sha=sha)


@method_decorator(csrf_exempt, name='dispatch')
class ApiUpdateSnapshot(generic.View):
    def post(self, request, sha):
        from .operation import on_batch_callback

        # if request.META.get('X-GitHub-Event') == 'push':
            # # to validate it in the future
            # event = DbWebhookEvent(source='github', content=request.data.decode('utf-8'),
            #                        signature=request.headers.get('X-Hub-Signature'))
            # db.session.add(event)
            # db.session.commit()
            #
            # client_id = request.args.get('client_id')
            # if not client_id:
            #     return 'Forbidden', 401
            #
            # key = DbAccessKey.query.filter_by(name=client_id).one_or_none()
            # if not key:
            #     # unknown client
            #     return 'Forbidden', 401
            #
            # if not validate_github_webhook(request, key.key1):
            #     return 'Invalid request', 403
            #
            # msg = on_github_push(request.json)
            #
            # return msg, 200
            # return HttpResponse(400)
        if request.META.get('HTTP_X_BATCH_EVENT') == 'build.finished':
            # event = DbWebhookEvent(source='batch', content=request.data.decode('utf-8'))
            # db.session.add(event)
            # db.session.commit()

            # the callback's credential is validated in on_batch_callback
            return on_batch_callback(request, sha)

        return HttpResponse(status=200)


def index(request):
    return render(request, 'morocco/index.html', context={'title': 'Azure CLI'})


def snapshot(request, sha):
    from .models import Snapshot

    data = get_object_or_404(Snapshot, sha=sha)
    cb = request.build_absolute_uri(reverse('morocco:api_update_snapshot', kwargs={'sha': sha}))
    return render(request, 'morocco/snapshot.html',
                  context={'title': 'Snapshot', 'data': data, 'cb': cb})


def sync_snapshots(request):
    # Sync the latest 100 snapshots
    import requests
    from .services import github
    from .models import Snapshot

    if request.method == 'POST':
        next_url = github.get_commits_api_url()
        count = 0
        while count < 100:
            response = requests.get(next_url)
            next_url = response.headers.get('link').split(',')[0].split(';')[0][1:-1]

            commits = response.json()

            for commit in commits:
                count += 1
                if not Snapshot.objects.filter(sha__exact=commit['sha']).exists():
                    record = Snapshot()
                    record.update_from_commit(commit)
                    record.save()

    return redirect('morocco:snapshots')


def manager(request):
    return render(request, 'morocco/manager.html')
