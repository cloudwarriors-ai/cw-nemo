import os
import logging
import requests

logger = logging.getLogger(__name__)


class GitHubBot:
    """GitHub API client using personal access token for creating issues"""

    def __init__(self):
        logger.info("Initializing GitHub Bot")
        self.token = os.environ.get('GITHUB_TOKEN')

        # Log credential status
        logger.info(f"GitHub Token: {'✓ Present' if self.token else '✗ Missing'}")

        if not self.token:
            logger.warning("Missing GITHUB_TOKEN - issue creation will be disabled")
            self.enabled = False
        else:
            self.enabled = True

        logger.info("GitHub Bot initialized")

    def _get_headers(self):
        """Get headers for GitHub API requests"""
        return {
            'Authorization': f'Bearer {self.token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28'
        }

    def create_issue(self, repo, title, body):
        """
        Create an issue in a GitHub repository

        Args:
            repo: Repository in format "owner/repo"
            title: Issue title
            body: Issue description/body

        Returns:
            tuple: (issue_number, issue_url) or (None, None) on failure
        """
        if not self.enabled:
            logger.error("GitHub Bot is not enabled - missing GITHUB_TOKEN")
            return None, None

        try:
            owner, repo_name = repo.split('/')
        except ValueError:
            logger.error(f"Invalid repo format: {repo}. Expected 'owner/repo'")
            return None, None

        try:
            url = f"https://api.github.com/repos/{repo}/issues"
            data = {
                'title': title,
                'body': body
            }

            logger.info(f"Creating issue in {repo}: {title}")
            response = requests.post(url, headers=self._get_headers(), json=data)
            response.raise_for_status()

            issue_data = response.json()
            issue_number = issue_data['number']
            issue_url = issue_data['html_url']

            logger.info(f"Successfully created issue #{issue_number}: {issue_url}")
            return issue_number, issue_url

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error creating issue: {e.response.status_code} - {e.response.text}")
            return None, None
        except Exception as e:
            logger.error(f"Error creating issue: {str(e)}", exc_info=True)
            return None, None

    def validate_repo_access(self, repo):
        """
        Check if the token has access to a repository

        Args:
            repo: Repository in format "owner/repo"

        Returns:
            bool: True if access is valid, False otherwise
        """
        if not self.enabled:
            return False

        try:
            url = f"https://api.github.com/repos/{repo}"
            response = requests.get(url, headers=self._get_headers())

            if response.status_code == 200:
                repo_data = response.json()
                return repo_data.get('has_issues', False)

            return False

        except Exception as e:
            logger.error(f"Error validating repo access: {str(e)}", exc_info=True)
            return False


# Initialize the bot when Django starts
logger.info("Attempting to initialize GitHub bot")
try:
    github_bot = GitHubBot()
    logger.info("GitHub bot initialized successfully")
except Exception as e:
    logger.error("Failed to initialize GitHub bot", exc_info=True)
    github_bot = None
