import requests
import logging
import os
import base64
from datetime import datetime, timedelta
from typing import Callable, Union

from azure.batch import BatchServiceClient
from azure.batch.models import (TaskAddParameter, JobAddParameter, JobPreparationTask, JobManagerTask, PoolInformation,
                                OutputFile, OutputFileDestination, OutputFileUploadOptions, OutputFileUploadCondition,
                                OutputFileBlobContainerDestination, OnAllTasksComplete, EnvironmentSetting,
                                ResourceFile, MetadataItem, CloudJob, CloudTask, CloudPool, TaskDependencies,
                                BatchErrorException)
from azure.storage.blob import ContainerPermissions, BlockBlobService

from .models import Setting


class GithubService(object):
    def __init__(self):
        from urllib.parse import urlparse

        self.source_url = Setting.objects.get(name__exact='GITHUB_SOURCE_URL').value
        self.branch = 'master'
        _, self.owner, self.repo = urlparse(self.source_url).path.split('/')
        self.repo = self.repo[:-4]

        self.client_id = Setting.objects.get(name__exact='GITHUB_CLIENT_ID').value
        self.client_secret = Setting.objects.get(name__exact='GITHUB_CLIENT_SECRET').value

    def __str__(self):
        return f'<Github source: {self.source_url} / {self.owner} / {self.repo}>'

    def get_commits_api_url(self, since: str = None, commit_sha: str = None) -> str:
        from urllib.parse import urlencode

        params = {'client_id': self.client_id, 'client_secret': self.client_secret}
        if since:
            params['since'] = since

        query = urlencode(params)

        if not commit_sha:
            return f'https://api.github.com/repos/{self.owner}/{self.repo}/commits?{query}'
        else:
            return f'https://api.github.com/repos/{self.owner}/{self.repo}/commits/{commit_sha}?{query}'

    def get_latest_commit(self) -> dict:
        return requests.get(self.get_commits_api_url()).json()[0]

    def get_commit(self, sha: str) -> dict:
        return requests.get(self.get_commits_api_url(commit_sha=sha)).json()


class AzureBatchClient(object):
    def __init__(self, source_control: GithubService, storage: BlockBlobService):
        from azure.batch.batch_auth import SharedKeyCredentials
        batch_account = Setting.objects.get(name__exact='BATCH_ACCOUNT').value
        batch_account_key = Setting.objects.get(name__exact='BATCH_ACCOUNT_KEY').value
        batch_account_endpoint = Setting.objects.get(name__exact='BATCH_ACCOUNT_ENDPOINT').value

        self.client = BatchServiceClient(SharedKeyCredentials(batch_account, batch_account_key), batch_account_endpoint)
        self.logger = logging.getLogger(AzureBatchClient.__name__)
        self.source = source_control
        self.storage = storage

    def get_batch_pool(self, usage: str) -> CloudPool:
        for pool in self.client.pool.list():
            if next(m.value for m in pool.metadata if m.name == 'usage') == usage:
                return pool

        raise EnvironmentError('Fail to find a pool.')

    def get_job(self, job_id: str) -> Union[CloudJob, None]:
        try:
            return self.client.job.get(job_id)
        except BatchErrorException:
            return None

    def delete_job(self, job_id: str) -> None:
        self.client.job.delete(job_id)

    def get_task(self, job_id: str, task_id: str) -> CloudTask:
        return self.client.task.get(job_id=job_id, task_id=task_id)

    def create_build_job(self, commit_sha: str, get_api_endpoint: Callable) -> CloudJob:
        """
        Schedule a build job in the given pool. returns the container for build output and job reference.

        Building and running tests are two separate builds so that the testing job can relies on job preparation tasks to
        prepare test environment. The product and test build is an essential part of the preparation. The builds can't be
        combined because the preparation task has to be defined by the time the job is created. However neither the product
        or the test package is ready then.

        The parameter request is required to generate absolute uri to the api endpoint
        """
        remote_source_dir = 'gitsrc'
        pool = self.get_batch_pool('build')

        if not pool:
            self.logger.error('Cannot find a build pool. Please check the pools list in config file.')
            raise ValueError('Fail to find a build pool.')

        # secret is a random string used to verify the identity of caller when one task requests the service to do
        # something. the secret is saved to the job definition as metadata, and it is passed to some tasks as well.
        secret = base64.b64encode(os.urandom(64)).decode('utf-8')

        job_metadata = [MetadataItem('usage', 'build'),
                        MetadataItem('secret', secret),
                        MetadataItem('source_url', self.source.source_url),
                        MetadataItem('source_sha', commit_sha)]

        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        job_id = f'build-{commit_sha}-{timestamp}'

        self.logger.info('Creating build job %s in pool %s', job_id, pool.id)
        self.client.job.add(JobAddParameter(id=job_id,
                                            pool_info=PoolInformation(pool.id),
                                            on_all_tasks_complete=OnAllTasksComplete.terminate_job,
                                            metadata=job_metadata,
                                            uses_task_dependencies=True))
        self.logger.info('Job %s is created.', job_id)

        output_file_name = 'azure-cli-{}.tar'.format(commit_sha)
        build_commands = [
            'git clone --depth=50 {} {}'.format(self.source.source_url, remote_source_dir),
            'pushd {}'.format(remote_source_dir),
            'git checkout -qf {}'.format(commit_sha),
            './scripts/batch/build_all.sh',
            'tar cvzf {} ./artifacts'.format(output_file_name)
        ]

        build_container_url = self._get_build_blob_container_url()

        output_file = OutputFile('{}/{}'.format(remote_source_dir, output_file_name),
                                 OutputFileDestination(OutputFileBlobContainerDestination(build_container_url,
                                                                                          output_file_name)),
                                 OutputFileUploadOptions(OutputFileUploadCondition.task_success))

        build_task = TaskAddParameter(id='build',
                                      command_line=self.get_command_string(*build_commands),
                                      display_name='Build all product and test code.',
                                      output_files=[output_file])

        url = get_api_endpoint('morocco:api_update_snapshot', sha=commit_sha)
        cmd = 'curl -X post {} -H "X-Batch-Event: build.finished" --data-urlencode secret={} --data-urlencode job_id={}'
        report_cmd = cmd.format(url, secret, job_id)

        report_task = TaskAddParameter(id='report',
                                       command_line=self.get_command_string(report_cmd),
                                       depends_on=TaskDependencies(task_ids=[build_task.id]),
                                       display_name='Request service to pull result')

        self.client.task.add(job_id, build_task)
        self.client.task.add(job_id, report_task)
        self.logger.info('Build task is added to job %s', job_id)

        return self.client.job.get(job_id)

    def _get_build_blob_container_url(self) -> str:
        self.storage.create_container('builds', fail_on_exist=False)
        return self.storage.make_blob_url(
            container_name='builds',
            blob_name='',
            protocol='https',
            sas_token=self.storage.generate_container_shared_access_signature(
                container_name='builds',
                permission=ContainerPermissions(list=True, write=True),
                expiry=(datetime.utcnow() + timedelta(days=1))))

    @staticmethod
    def get_command_string(*args) -> str:
        return "/bin/bash -c 'set -e; set -o pipefail; {}; wait'".format(';'.join(args))


def get_blob_storage() -> BlockBlobService:
    storage_account = Setting.objects.get(name__exact='STORAGE_ACCOUNT').value
    storage_account_key = Setting.objects.get(name__exact='STORAGE_ACCOUNT_KEY').value

    return BlockBlobService(account_name=storage_account, account_key=storage_account_key)


github = GithubService()
blob_storage = get_blob_storage()
azure_batch = AzureBatchClient(source_control=github, storage=blob_storage)
