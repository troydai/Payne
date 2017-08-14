from typing import List, Union, Tuple
from datetime import datetime, timedelta

from azure.batch.models import MetadataItem, CloudJob, JobState
from azure.storage.blob.models import BlobPermissions

from django.db.models import ObjectDoesNotExist
from django.shortcuts import get_object_or_404, reverse
from django.http import HttpRequest, HttpResponse

from .models import Snapshot
from .services import github, blob_storage, azure_batch


def rebuild_snapshot(sha: str, request: HttpRequest) -> Tuple[Snapshot, CloudJob]:
    def get_api_endpoint(endpoint: str, **kwargs) -> str:
        if request:
            return request.build_absolute_uri(reverse(endpoint, kwargs=kwargs))
        else:
            return ''

    snapshot = get_object_or_404(Snapshot, sha=sha)
    if snapshot.batch_job_id:
        job = azure_batch.get_job(snapshot.batch_job_id)
        if job and job.state != JobState.completed:
            return snapshot, job

    job = azure_batch.create_build_job(sha, get_api_endpoint)
    snapshot.batch_job_id = job.id
    snapshot.batch_job_last_update = datetime.utcnow()
    snapshot.batch_job_create = job.creation_time
    snapshot.save()

    return snapshot, job


def refresh_snapshot(sha: str = None, commit: dict = None):
    if not commit and not sha:
        raise ValueError('Missing commit')

    if not commit:
        if sha == '<latest>':
            commit = github.get_latest_commit()
        else:
            commit = commit or github.get_commit(sha)

    sha = commit['sha']

    try:
        snapshot = Snapshot.objects.get(sha__exact=sha)
    except ObjectDoesNotExist:
        snapshot = Snapshot()
        snapshot.update_from_commit(commit)

    if snapshot.batch_job_id:
        batch_job = azure_batch.get_job(snapshot.batch_job_id)
        snapshot.batch_job_last_update = datetime.utcnow()
        if batch_job:
            # build job can be deleted. it is not required to keep data in sync
            build_task = azure_batch.get_task(job_id=batch_job.id, task_id='build')
            if build_task:
                snapshot.state = build_task.state.value
                snapshot.batch_job_id = batch_job.id
                snapshot.batch_job_create = batch_job.creation_time
        else:
            snapshot.batch_job_id = None
            snapshot.batch_job_create = None

    blob = 'azure-cli-{}.tar'.format(sha)
    if blob_storage.exists(container_name='builds', blob_name=blob):
        snapshot.download_url = blob_storage.make_blob_url(
            'builds', blob_name=blob, protocol='https', sas_token=blob_storage.generate_blob_shared_access_signature(
                'builds', blob, BlobPermissions(read=True), expiry=datetime.utcnow() + timedelta(days=365)))

    snapshot.save()
    return snapshot


def ignore_snapshot(sha: str) -> None:
    snapshot = get_object_or_404(Snapshot, sha__exact=sha)
    snapshot.ignore = True
    snapshot.save()


def on_batch_callback(request: HttpRequest, sha: str) -> HttpResponse:
    data = request.POST.dict()

    secret = data.get('secret')
    if 'secret' not in request.POST:
        return HttpResponse(content='Missing secret', status=403)

    job = azure_batch.get_job(data.get('job_id'))
    if not job:
        return HttpResponse(content='Cloud job is not found', status=400)

    expect_secret = get_metadata(job.metadata, 'secret')
    if expect_secret != secret:
        return HttpResponse(content='Invalid secret', status=403)

    refresh_snapshot(sha)

    return HttpResponse(content=f'Snapshot {sha} is updated.', status=200)


def get_metadata(metadata: List[MetadataItem], name: str) -> Union[str, None]:
    for each in metadata or []:
        if each.name == name:
            return each.value
    return None
