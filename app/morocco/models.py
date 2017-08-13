from datetime import datetime

from django.db import models


class Setting(models.Model):
    name = models.CharField(max_length=128)
    value = models.CharField(max_length=512)

    def __str__(self):
        return self.name


class Snapshot(models.Model):
    sha = models.CharField(max_length=40)

    commit_author = models.CharField(max_length=128)
    commit_message = models.CharField(max_length=1024)
    commit_date = models.DateTimeField()
    commit_url = models.CharField(max_length=1024)
    ignore = models.BooleanField()

    batch_job_id = models.CharField(max_length=200, null=True)
    batch_job_create = models.DateTimeField(null=True)
    batch_job_last_update = models.DateTimeField(null=True)

    download_url = models.CharField(max_length=2048, null=True)

    def update_from_commit(self, commit_json) -> None:
        self.sha = commit_json['sha']
        self.commit_author = commit_json['commit']['author']['name'][:128]
        self.commit_date = datetime.strptime(commit_json['commit']['committer']['date'], '%Y-%m-%dT%H:%M:%SZ')
        self.commit_message = commit_json['commit']['message'][:1024]
        self.commit_url = commit_json['html_url'][:1024]
        if self.commit_author == 'azuresdkci':
            self.ignore = True
        else:
            self.ignore = False

    @property
    def short_sha(self) -> str:
        return self.sha[:7]

    @property
    def commit_subject(self) -> str:
        return self.commit_message.strip().split('\n')[0]

    @property
    def commit_date_str(self) ->str:
        return self.commit_date.strftime('%Y-%m-%d')

    def __str__(self):
        return self.sha


class TestRun(models.Model):
    snapshot = models.ForeignKey(Snapshot, on_delete=models.CASCADE)
