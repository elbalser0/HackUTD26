import pytest

from breakglass import tfrunner
from breakglass.tfrunner import APPLY_PLAN, SCAN_PLAN, RunResult, Terraform, TerraformError

FAKE_TOKEN = "dop_v1_fake"


class Rec:
    def __init__(self, result=RunResult(0, "", "")):
        self.result = result
        self.calls = []

    def __call__(self, args, cwd, timeout, stream):
        self.calls.append((args, cwd, timeout, stream))
        return self.result


def tf_with(tmp_path, code=0, stdout="", stderr=""):
    r = Rec(RunResult(code, stdout, stderr))
    return Terraform(tmp_path, runner=r, binary="tfbin"), r


@pytest.mark.parametrize("code,expected", [(0, False), (2, True)])
def test_plan_detailed_exitcode(tmp_path, code, expected):
    tf, r = tf_with(tmp_path, code)
    assert tf.plan(APPLY_PLAN) is expected
    args = r.calls[0][0]
    assert "-detailed-exitcode" in args and f"-out={APPLY_PLAN}" in args
    assert "-refresh-only" not in args


def test_plan_exit_1_raises(tmp_path):
    tf, _ = tf_with(tmp_path, 1, stderr="Error: boom")
    with pytest.raises(TerraformError, match="boom"):
        tf.plan(APPLY_PLAN)


def test_refresh_only_inserts_flag(tmp_path):
    tf, r = tf_with(tmp_path, 2)
    tf.plan(SCAN_PLAN, refresh_only=True)
    args = r.calls[0][0]
    assert args[:3] == ["tfbin", "plan", "-refresh-only"]


@pytest.mark.parametrize("name", ["evil.tfplan", "../x.tfplan", "-destroy", "/tmp/p"])
def test_arbitrary_plan_names_rejected(tmp_path, name):
    tf, r = tf_with(tmp_path)
    with pytest.raises(ValueError):
        tf.plan(name)
    with pytest.raises(ValueError):
        tf.show_json(name)
    assert r.calls == []


def test_apply_saved_rejects_scan_plan(tmp_path):
    tf, r = tf_with(tmp_path)
    with pytest.raises(ValueError):
        tf.apply_saved(SCAN_PLAN)
    with pytest.raises(ValueError):
        tf.apply_saved("other.tfplan")
    assert r.calls == []


def test_runner_receives_list_and_cwd(tmp_path):
    tf, r = tf_with(tmp_path, 0, stdout="{}")
    tf.workspace()
    tf.plan(APPLY_PLAN)
    tf.show_json(APPLY_PLAN)
    tf.apply_saved(APPLY_PLAN)
    assert len(r.calls) == 4
    for args, cwd, timeout, stream in r.calls:
        assert isinstance(args, list) and all(isinstance(a, str) for a in args)
        assert args[0] == "tfbin"
        assert cwd == tmp_path
    assert r.calls[-1][0] == ["tfbin", "apply", "-input=false", "-lock-timeout=30s", APPLY_PLAN]
    assert r.calls[-1][3] is True


def test_show_json_invalid(tmp_path):
    tf, _ = tf_with(tmp_path, 0, stdout="not json")
    with pytest.raises(TerraformError):
        tf.show_json(APPLY_PLAN)
    tf2, _ = tf_with(tmp_path, 0, stdout="[1,2]")
    with pytest.raises(TerraformError):
        tf2.show_json(APPLY_PLAN)


def test_child_env_reads_token_file(tmp_path, monkeypatch):
    tok = tmp_path / "tok"
    tok.write_text(FAKE_TOKEN + "\n", encoding="utf-8")
    monkeypatch.delenv("DIGITALOCEAN_TOKEN", raising=False)
    monkeypatch.setenv("BG_DO_TOKEN_FILE", str(tok))
    env = tfrunner.child_env()
    assert env["DIGITALOCEAN_TOKEN"] == FAKE_TOKEN
    assert env["TF_IN_AUTOMATION"] == "1" and env["TF_INPUT"] == "0"
    import os
    assert "DIGITALOCEAN_TOKEN" not in os.environ  # child env only


def test_child_env_prefers_existing_env(tmp_path, monkeypatch):
    tok = tmp_path / "tok"
    tok.write_text(FAKE_TOKEN, encoding="utf-8")
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "from_env")
    monkeypatch.setenv("BG_DO_TOKEN_FILE", str(tok))
    assert tfrunner.child_env()["DIGITALOCEAN_TOKEN"] == "from_env"


def test_child_env_missing_token_file(tmp_path, monkeypatch):
    monkeypatch.delenv("DIGITALOCEAN_TOKEN", raising=False)
    monkeypatch.setenv("BG_DO_TOKEN_FILE", str(tmp_path / "nope"))
    assert "DIGITALOCEAN_TOKEN" not in tfrunner.child_env()


def test_token_not_in_error_messages(tmp_path, monkeypatch):
    tok = tmp_path / "tok"
    tok.write_text(FAKE_TOKEN, encoding="utf-8")
    monkeypatch.delenv("DIGITALOCEAN_TOKEN", raising=False)
    monkeypatch.setenv("BG_DO_TOKEN_FILE", str(tok))
    stderr = "Error: 401 Unauthorized"
    for call in (lambda t: t.plan(APPLY_PLAN), lambda t: t.workspace(), lambda t: t.show_json(APPLY_PLAN)):
        tf, _ = tf_with(tmp_path, 1, stderr=stderr)
        with pytest.raises(TerraformError) as ei:
            call(tf)
        msg = str(ei.value)
        assert FAKE_TOKEN not in msg
        assert "401 Unauthorized" in msg


def test_config_hash_tracks_tf_files_only(tmp_path):
    (tmp_path / "main.tf").write_text("a", encoding="utf-8")
    tf = Terraform(tmp_path, runner=Rec())
    h0 = tf.config_hash()
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    (tmp_path / APPLY_PLAN).write_bytes(b"plan")
    (tmp_path / "terraform.tfstate").write_text("{}", encoding="utf-8")
    assert tf.config_hash() == h0
    (tmp_path / "main.tf").write_text("b", encoding="utf-8")
    h1 = tf.config_hash()
    assert h1 != h0
    (tmp_path / "vars.tfvars").write_text("x=1", encoding="utf-8")
    assert tf.config_hash() != h1


def test_plan_hash_and_cleanup(tmp_path):
    tf = Terraform(tmp_path, runner=Rec())
    assert tf.plan_hash(APPLY_PLAN) is None
    (tmp_path / APPLY_PLAN).write_bytes(b"a")
    (tmp_path / SCAN_PLAN).write_bytes(b"b")
    assert tf.plan_hash(APPLY_PLAN).startswith("sha256:")
    tf.cleanup()
    assert not (tmp_path / APPLY_PLAN).exists() and not (tmp_path / SCAN_PLAN).exists()
    tf.cleanup()  # idempotent
