import subprocess

import pytest

from conftest import ME, minimal


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@x", *args], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout


@pytest.fixture
def remote(cat, repo, tmp_path):
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", "-q", "-b", "main", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "-u", "origin", "HEAD")
    return bare


def test_unpushed_commits_are_retried(cat, repo, remote, tmp_path):
    git(repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    cat.save_dataset(minimal(), ME, create=True)
    assert cat.sync_error and cat.git.unpushed() == 1
    git(repo, "remote", "set-url", "origin", str(remote))
    cat.sync()
    assert cat.sync_error is None and cat.git.unpushed() == 0
    assert "Test study" in git(remote, "show", "HEAD:datasets/2020-test-study.yaml")


def test_conflict_is_aborted_cleanly(cat, repo, remote, tmp_path, client):
    cat.save_dataset(minimal(), ME, create=True)
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(remote), str(other))
    f = other / "datasets/2020-test-study.yaml"
    f.write_text(f.read_text().replace("title: Test study", "title: Changed on GitHub"))
    git(other, "commit", "-qam", "edit on GitHub")
    # an edit here while GitHub can't be reached, so it can't be rebased first
    git(repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    cat.save_dataset(minimal(title="Changed in the app"), ME)
    git(other, "push", "-q")
    git(repo, "remote", "set-url", "origin", str(remote))
    cat.sync()
    assert "conflict" in cat.sync_error
    assert not cat.git.rebase_in_progress() and not git(repo, "status", "--porcelain").strip()
    assert cat.datasets["2020-test-study"].title == "Changed in the app"
    assert "Not in sync with GitHub" not in client.get("/").text
    client.app.state.cat.sync_error = cat.sync_error
    assert "Not in sync with GitHub" in client.get("/").text


def test_admin_page_and_sync_button(repo, remote, tmp_path):
    from fastapi.testclient import TestClient

    from labcat.config import Settings
    from labcat.web import create_app

    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(remote), str(other))
    (other / "datasets/2021-by-hand.yaml").write_text("id: 2021-by-hand\ntitle: Edited by hand\ncontact: matthias\n")
    git(other, "add", "-A")
    git(other, "commit", "-qm", "hand edit")
    git(other, "push", "-q")

    admin = TestClient(create_app(Settings(data_dir=repo, user="matthias", admins=("matthias",), pull_interval=0)),
                       follow_redirects=False)
    page = admin.get("/admin").text
    assert "In sync." in page and str(remote) in page and 'href="/admin"' in page
    assert admin.get("/d/2021-by-hand").status_code == 404
    assert admin.post("/admin/sync").headers["location"] == "/admin"
    assert admin.get("/d/2021-by-hand").status_code == 200

    user = TestClient(create_app(Settings(data_dir=repo, user="matthias")), follow_redirects=False)
    assert user.get("/admin").status_code == 403 and user.post("/admin/sync").status_code == 403
    assert 'href="/admin"' not in user.get("/").text


def test_token_answers_credential_requests(cat):
    from labcat.gitrepo import GitRepo

    repo = GitRepo(cat.root, "Lab catalog", "catalog@lab.local", token="secret-token")
    out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                         env=repo.env(), capture_output=True, text=True, check=True).stdout
    assert "username=x-access-token" in out and "password=secret-token" in out


def test_app_clones_missing_data_repo(repo, remote, tmp_path):
    from labcat.config import Settings
    from labcat.web import create_app

    target = tmp_path / "clone" / "data"
    create_app(Settings(data_dir=target, user="matthias", data_remote=str(remote), pull_interval=0))
    assert (target / ".git").exists()
    assert git(target, "rev-parse", "HEAD") == git(repo, "rev-parse", "HEAD")


def test_clone_refuses_non_empty_dir(tmp_path):
    from labcat.gitrepo import GitError, GitRepo

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x").write_text("x")
    with pytest.raises(GitError):
        GitRepo(tmp_path / "data", "n", "e").clone(str(tmp_path / "nowhere.git"))


def test_sandbox_never_pushes_and_resets_on_sync(cat, repo, remote):
    cat.sandbox = True
    before = git(remote, "rev-parse", "HEAD")
    cat.save_dataset(minimal(), ME, create=True)
    assert git(remote, "rev-parse", "HEAD") == before
    assert "2020-test-study" in cat.datasets
    cat.sync()
    assert cat.sync_error is None
    assert git(repo, "rev-parse", "HEAD") == before
    assert "2020-test-study" not in cat.datasets


def test_sandbox_banner(repo):
    from fastapi.testclient import TestClient
    from labcat.config import Settings
    from labcat.web import create_app

    client = TestClient(create_app(Settings(data_dir=repo, user="matthias", sandbox=True)))
    assert "Test copy." in client.get("/").text


def test_app_replaces_checkout_of_another_repo(remote, tmp_path):
    from labcat.config import Settings
    from labcat.store import init_data_repo
    from labcat.web import create_app

    other = tmp_path / "slot" / "data"
    init_data_repo(other, ME)  # no remote, like a fresh `labcat init`
    create_app(Settings(data_dir=other, user="matthias", data_remote=str(remote) + "/", pull_interval=0))
    assert git(other, "rev-parse", "HEAD") == git(remote, "rev-parse", "HEAD")
    assert len(list(other.parent.glob("data.old-*"))) == 1


def test_app_keeps_matching_checkout(repo, remote, tmp_path):
    from labcat.config import Settings
    from labcat.web import create_app

    create_app(Settings(data_dir=repo, user="matthias", data_remote=str(remote), pull_interval=0))
    assert not list(repo.parent.glob("data.old-*"))


def test_same_remote():
    from labcat.gitrepo import same_remote

    assert same_remote("https://github.com/a/b.git", "https://x:tok@github.com/A/b/")
    assert not same_remote("https://github.com/a/b.git", "https://github.com/a/c.git")
    assert not same_remote(None, "https://github.com/a/b.git")
