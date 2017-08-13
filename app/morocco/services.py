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

    @property
    def commits_api_url(self, since: str = None) -> str:
        from urllib.parse import urlencode

        params = {'client_id': self.client_id, 'client_secret': self.client_secret}
        if since:
            params['since'] = since

        query = urlencode(params)

        return f'https://api.github.com/repos/{self.owner}/{self.repo}/commits?{query}'


github = GithubService()
