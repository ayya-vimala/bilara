import pathlib
from collections import defaultdict
from git import Repo, GitCommandError
from config import config


import threading
import time

import notify

import atexit

_lock = threading.RLock()
PUSH_DELAY = 15

from config import config
GIT_REMOTE_REPO = config.GIT_REMOTE_REPO
REPO_DIR = config.REPO_DIR
CHECKOUTS_DIR = config.CHECKOUTS_DIR

if REPO_DIR.exists():
    base_repo = Repo(REPO_DIR)
else:
    print('Pulling Repo (one time only)')
    base_repo = Repo.clone_from(GIT_REMOTE_REPO, REPO_DIR, multi_options=['--no-checkout'])

class Branch:
    repo = None
    branch = None
    path = None
    name = None

    def get_checkout_dir(self):
        return CHECKOUTS_DIR / self.name

    @property
    def branch(self):
        return self.repo.active_branch

    def get_or_create_repo(self):
        return Repo.clone_from(
            GIT_REMOTE_REPO,
            self.path,
            multi_options=[f'--reference={REPO_DIR}', '--single-branch', f'--branch={branch_name}']
        )
    def __init__(self, branch_name):        
        self.name = branch_name
        self.path = self.get_checkout_dir()
        if self.path.exists():
            self.repo = Repo(self.path)
        else:
            self.repo = self.get_or_create_repo()
        

published = Branch(config.PUBLISHED_BRANCH_NAME)
unpublished = Branch(config.UNPUBLISHED_BRANCH_NAME)
#review = Branch(config.REVIEW_BRANCH_NAME)

git = unpublished.repo.git

def create_empty_commit(user, branch_name):
    git.commit(allow_empty=True, m=f'Translations by {user["login"]}', author=f'{user["name"]} <{user["email"]}>')
    _pending_commits[branch_name] = time.time()

_pending_commit = None

def update_file(file, user):
    global _pending_commit
    branch = unpublished.branch
    file = str(file).lstrip('/')
    with _lock:
        commit_message = f'Translations by {user["login"]} to {file}'

        if _pending_commit and branch.commit.message == commit_message:
            # We can add onto this commit
            git.add(file)
            git.commit(amend=True, no_edit=True)
        else:
            finalize_commit()

            git.add(file)
            try:
                git.commit(m=commit_message, author=f'{user.get("name") or user["login"]} <{user["email"]}>')
                _pending_commit = branch.commit
            except GitCommandError as e:
                if e.status == 1 and ('nothing to commit' in e.stdout or 'nothing added to commit' in e.stdout):
                    # This is unusual but fine
                    pass
                else:
                    raise

def update_files(user, files):
    global _pending_commit
    with _lock:
        if _pending_commit:
            finalize_commit()

        git.add(files)
        git.commit(m=f"Bulk update", author=f'{user["name"] or user["login"]} <{user["email"]}>')
        finalize_commit()

def githook(webhook_payload, branch_name=unpublished.name):
    ref = webhook_payload['ref'].split('/')[-1]
    if ref != branch_name:
        return
    
    added = []
    modified = []
    removed = []
    
    for commit in webhook_payload['commits']:
        if commit['id'] == unpublished.branch.commit.hexsha:
            return 
        added.extend(commit['added'])
        modified.extend(commit['modified'])
        removed.extend(commit['removed'])
    
    print(f'{len(added)} added, {len(modified)} modified, {len(removed)} removed')
    with _lock:
        if _pending_commit:
            finalize_commit()
        git.pull('-Xtheirs')

    if added or removed:
        import app
        app.init()

    
    from search import search
    #search.files_removed([( filepath, get_deleted_file_data(filepath) ) for filepath in removed])
    search.update_partial(added, modified)


def get_publication_line_counts():
    file_stats = base_repo.git.diff('unpublished..published', '--numstat')

    result = defaultdict(int)

    for line in file_stats.split('\n'):
        if line:
            added, deleted, filepath = line.split()
            result[filepath] = int(added)+int(deleted)
            parts = pathlib.Path(filepath).parts

            for i in range(0, len(parts)):
                result['/'.join(parts[0:i])] += 1

    return dict(result)

def get_file_map(branch_name):
    files = {}

    r = base_repo.git.ls_tree('-r', branch_name)
    
    for line in r.split('\n'):
        if line:
            p, t, sha, filepath  = line.split()
            files[filepath] = sha
    return files

def get_publication_state():
    published_files = get_file_map(published.name)
    unpublished_files = get_file_map(unpublished.name)

    result = defaultdict(lambda: {'PUBLISHED':0, 'UNPUBLISHED': 0, 'MODIFIED': 0})
    for filepath, sha in unpublished_files.items():
        if filepath not in published_files:
            state = 'UNPUBLISHED'
        else:
            if published_files[filepath] == sha:
                state = 'PUBLISHED'
            else:
                state = 'MODIFIED'
        result[filepath] = state

        parts = pathlib.Path(filepath).parts
        for i in range(0, len(parts)):
            result['/'.join(parts[0:i])][state] += 1
    
    return dict(result)
            
        



def finalize_commit():
    global _pending_commit
    if not _pending_commit:
        return
    
    if not config.GIT_SYNC_ENABLED:
        print('Not Pushing because disabled in config')
        _pending_commit = None
        return
    print(f'Pushing to {unpublished.name}... ', end='')
    for i in range(0, 3):
        try:
            git.push('-u', 'origin', unpublished.name)
            print('Success')
            break
        except GitCommandError:
            print('Git push failed, attempting to pull and trying again')
            if i <= 1:
                git.pull('-Xtheirs')
            
    else:
        print('Failure')
        print('Git push failed multiple times')
        notify.send_message_to_admin('Bilara failed to push to Github, this requires manual intervention', title='Bilara Push Fail')
        return
    _pending_commit = None


def finalizer_task_runner(interval):
    while True:
        time.sleep(interval)
        if not _pending_commit:
            continue
        
        with _lock:
            now = time.time()
            if not _pending_commit:
                continue
            if now - _pending_commit.committed_date > PUSH_DELAY:
                finalize_commit()

atexit.register(finalize_commit)

def start_finalizer(interval):
    finalizer = threading.Thread(target=finalizer_task_runner, args=(interval,))
    finalizer.daemon = True
    finalizer.start()
    return finalizer

_finalizer = start_finalizer(5)