from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404


def index(request):
    return render(request, 'morocco/index.html', context={'title': 'Azure CLI'})


def snapshots(request):
    from .models import Snapshot

    data = Snapshot.objects.filter(ignore=False).all()
    return render(request, 'morocco/snapshots.html', context={'title': 'Snapshots', 'data': data})


def snapshot(request, sha):
    from .models import Snapshot

    data = get_object_or_404(Snapshot, sha=sha)
    return render(request, 'morocco/snapshot.html', context={'title': 'Snapshot', 'data': data})


def sync_snapshots(request):
    # Sync the latest 100 snapshots
    import requests
    from .services import github
    from .models import Snapshot

    if request.method == 'POST':
        next_url = github.commits_api_url
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
