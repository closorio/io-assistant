import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sin_claude_git as s  # noqa: E402


def ev(cmd, cwd=""):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd}


def test_commit_con_trailer_se_deniega():
    cmd = "git commit -m \"$(cat <<'EOF'\nfix: algo\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\nEOF\n)\""
    assert s.decidir(ev(cmd))["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_commit_limpio_pasa_aunque_la_ruta_tenga_punto_claude():
    cmd = 'cd "/x/.claude/worktrees/rama" && git add CLAUDE.md && git commit -m "docs: actualizar CLAUDE.md"'
    assert s.decidir(ev(cmd)) is None


def test_pr_con_generated_with_se_deniega():
    cmd = 'gh pr create --title "x" --body "hola\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)"'
    assert s.decidir(ev(cmd)) is not None


def test_git_push_dentro_de_un_texto_no_cuenta(tmp_path):
    cwd = _repo(tmp_path, "fix\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
    cmd = "python3 - <<'EOF'\ns='deniega git commit, git push y gh pr create'\nEOF"
    assert s.decidir(ev(cmd, cwd)) is None


def test_push_tras_cd_si_cuenta(tmp_path):
    cwd = _repo(tmp_path, "fix\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
    assert s.decidir(ev(f'cd "{cwd}" && git push origin HEAD', cwd)) is not None


def test_lo_que_va_tras_el_commit_no_cuenta():
    assert s.decidir(ev('git commit -m "fix: x" && git log | grep -c anthropic')) is None


def test_otros_comandos_pasan():
    assert s.decidir(ev("ls ~/.claude && echo claude")) is None


def _repo(tmp_path, mensaje):
    remoto = tmp_path / "remoto.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remoto)], check=True)
    r = tmp_path / "r"
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    g = ["git", "-C", str(r), "-c", "user.name=a", "-c", "user.email=a@b.c"]
    subprocess.run(g + ["commit", "-q", "--allow-empty", "-m", "base"], check=True)
    subprocess.run(g + ["remote", "add", "origin", str(remoto)], check=True)
    subprocess.run(g + ["push", "-q", "origin", "HEAD:main"], check=True)
    subprocess.run(g + ["fetch", "-q", "origin"], check=True)
    subprocess.run(g + ["commit", "-q", "--allow-empty", "-m", mensaje], check=True)
    return str(r)


def test_push_con_commit_firmado_se_deniega(tmp_path):
    cwd = _repo(tmp_path, "fix\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
    assert s.decidir(ev("git push origin HEAD", cwd)) is not None


def test_push_limpio_pasa(tmp_path):
    cwd = _repo(tmp_path, "fix: limpio")
    assert s.decidir(ev("git push origin HEAD", cwd)) is None
