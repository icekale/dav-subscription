import json
from pathlib import Path

import pytest
import watchdog


class FakeCookies:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.set_calls = []
        self.jar = self

    def __iter__(self):
        return iter(
            type("Cookie", (), {"name": name, "value": value})
            for name, value in self.values.items()
        )

    def set(self, name, value, **kwargs):
        self.set_calls.append((name, value, kwargs))
        self.values[name] = value


class FakeResponse:
    def __init__(self, text, *, content_type="text/html", status_code=200, json_value=None):
        self.text = text
        self.headers = {"content-type": content_type}
        self.status_code = status_code
        self._json_value = json_value

    def json(self):
        if isinstance(self._json_value, BaseException):
            raise self._json_value
        return self._json_value


class FakeSession:
    def __init__(self, responses, cookies=None):
        self.responses = list(responses)
        self.cookies = FakeCookies(cookies)
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def target():
    return {
        "url": "https://xueqiu.com/",
        "out": "xueqiu",
        "seed_cookie": "",
    }


def write_old(path):
    path.write_text("old cookies", encoding="utf-8")


def test_refresh_uses_unique_temp_and_cleans_it_on_replace_failure(tmp_path, monkeypatch):
    output = tmp_path / "cookies.json"
    write_old(output)
    victim = tmp_path / "victim"
    victim.write_text("sentinel", encoding="utf-8")
    stale = Path(f"{output}.xueqiu.tmp")
    stale.symlink_to(victim)
    session = FakeSession(
        [
            FakeResponse("home", content_type="text/html"),
            FakeResponse("{}", content_type="application/json", json_value={"statuses": []}),
        ],
        {"acw_tc": "new"},
    )
    replaced = {}

    def fail_replace(source, destination):
        replaced["source"] = Path(source)
        replaced["destination"] = Path(destination)
        raise OSError("replace failed")

    monkeypatch.setattr(watchdog.os, "replace", fail_replace)

    assert not watchdog.refresh(target(), session=session, output=output)
    assert output.read_text(encoding="utf-8") == "old cookies"
    assert replaced["destination"] == output
    assert replaced["source"] != stale
    assert not replaced["source"].exists()
    assert stale.is_symlink()
    assert victim.read_text(encoding="utf-8") == "sentinel"


def test_refresh_serializes_duplicate_cookie_scopes(tmp_path):
    session = FakeSession(
        [
            FakeResponse("home", content_type="text/html"),
            FakeResponse("{}", content_type="application/json", json_value={"statuses": []}),
        ]
    )
    session.cookies = watchdog.requests.Cookies()
    session.cookies.set("same", "one", domain=".xueqiu.com", path="/")
    session.cookies.set("same", "two", domain="xueqiu.com", path="/")
    output = tmp_path / "cookies.json"

    assert watchdog.refresh(target(), session=session, output=output)
    assert json.loads(output.read_text(encoding="utf-8"))["cookies"] == [
        {"name": "same", "value": "one"},
        {"name": "same", "value": "two"},
    ]


def test_owned_session_closes_after_success(tmp_path, monkeypatch):
    session = FakeSession(
        [
            FakeResponse("home", content_type="text/html"),
            FakeResponse("{}", content_type="application/json", json_value={"statuses": []}),
        ],
        {"acw_tc": "ok"},
    )
    monkeypatch.setattr(watchdog.requests, "Session", lambda **kwargs: session)

    assert watchdog.refresh(target(), output=tmp_path / "cookies.json")
    assert session.closed


def test_owned_session_closes_after_failure(tmp_path, monkeypatch):
    session = FakeSession(
        [
            FakeResponse("home", content_type="text/html"),
            FakeResponse("bad", content_type="text/html", json_value=ValueError("bad json")),
        ],
        {"acw_tc": "intermediate"},
    )
    monkeypatch.setattr(watchdog.requests, "Session", lambda **kwargs: session)

    assert not watchdog.refresh(target(), output=tmp_path / "cookies.json")
    assert session.closed


def test_injected_session_remains_caller_owned(tmp_path):
    session = FakeSession(
        [
            FakeResponse("home", content_type="text/html"),
            FakeResponse("bad", content_type="text/html", json_value=ValueError("bad json")),
        ],
        {"acw_tc": "intermediate"},
    )

    assert not watchdog.refresh(target(), session=session, output=tmp_path / "cookies.json")
    assert not session.closed


def test_solver_rejects_whitespace_signed_url(monkeypatch):
    html = "<html>complete challenge HTML</html>"
    url = "https://xueqiu.com/"
    calls = {}

    class Completed:
        stdout = json.dumps({"signed_url": " \t\n"})

    def run(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr(watchdog.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="signed URL"):
        watchdog._solve_challenge(html, url)

    assert calls["command"] == [
        "node",
        "--permission",
        "--allow-fs-read=.",
        "--allow-fs-read=./node_modules",
        "./solver.js",
    ]
    assert calls["kwargs"]["cwd"] == str(watchdog.SOLVER.parent)
    assert not any(
        flag in " ".join(calls["command"])
        for flag in ("--allow-fs-write", "--allow-child-process", "--allow-worker")
    )
    assert calls["kwargs"].get("shell", False) is False
    assert json.loads(calls["kwargs"]["input"]) == {
        "html": html,
        "url": url,
        "user_agent": watchdog.UA,
    }
    assert calls["kwargs"]["text"] is True
    assert calls["kwargs"]["capture_output"] is True
    assert calls["kwargs"]["timeout"] == 10
    assert calls["kwargs"]["check"] is True


def test_challenge_solves_exact_html_and_publishes_verified_cookies(tmp_path):
    html = '<html>renderData<script>location="/signed?md5__1038=abc"</script></html>'
    session = FakeSession(
        [
            FakeResponse(html),
            FakeResponse("signed", content_type="text/html"),
            FakeResponse("{}", content_type="application/json", json_value={"statuses": [{}]}),
        ],
        {"acw_tc": "challenge", "xq_a_token": "token"},
    )
    solver_inputs = []

    def solve(challenge_html, url):
        solver_inputs.append((challenge_html, url))
        return "/signed?md5__1038=abc"

    output = tmp_path / "waf_cookies.json"
    assert watchdog.refresh(target(), session=session, solve=solve, output=output)
    assert solver_inputs == [(html, "https://xueqiu.com/")]
    assert session.calls[1][0] == "https://xueqiu.com/signed?md5__1038=abc"
    assert session.calls[1][1]["headers"]["Referer"] == "https://xueqiu.com/"
    assert session.calls[2][1]["params"] == watchdog.PROBE_PARAMS
    assert not session.closed
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["cookies"] == [
        {"name": "acw_tc", "value": "challenge"},
        {"name": "xq_a_token", "value": "token"},
    ]


def test_render_data_on_signed_response_preserves_old_file(tmp_path):
    output = tmp_path / "waf_cookies.json"
    write_old(output)
    session = FakeSession(
        [
            FakeResponse("<html>renderData challenge</html>"),
            FakeResponse("<html>renderData still here</html>"),
        ]
    )

    assert not watchdog.refresh(
        target(),
        session=session,
        solve=lambda html, url: "/signed?md5__1038=abc",
        output=output,
    )
    assert output.read_text(encoding="utf-8") == "old cookies"


def test_invalid_probe_json_preserves_old_file(tmp_path):
    output = tmp_path / "waf_cookies.json"
    write_old(output)
    session = FakeSession(
        [
            FakeResponse("home", content_type="text/html"),
            FakeResponse("not json", content_type="text/html", json_value=ValueError("bad json")),
        ],
        {"xq_a_token": "token"},
    )

    assert not watchdog.refresh(target(), session=session, output=output)
    assert output.read_text(encoding="utf-8") == "old cookies"


def test_seed_cookie_uses_auth_probe_and_10022_preserves_old_file(tmp_path):
    output = tmp_path / "waf_cookies.json"
    write_old(output)
    config = target()
    config["seed_cookie"] = "xq_a_token=token"
    session = FakeSession(
        [
            FakeResponse("home", content_type="text/html"),
            FakeResponse(
                "{}",
                content_type="application/json",
                json_value={"error_code": "10022", "error_description": ""},
            ),
        ],
        {"xq_a_token": "token"},
    )

    assert not watchdog.refresh(config, session=session, output=output)
    assert output.read_text(encoding="utf-8") == "old cookies"
    assert session.calls[1][0] == watchdog.AUTH_PROBE_URL
    assert session.calls[1][1]["params"] == watchdog.AUTH_PROBE_PARAMS


def test_seed_cookie_auth_probe_rejects_http_400(tmp_path):
    output = tmp_path / "waf_cookies.json"
    write_old(output)
    config = target()
    config["seed_cookie"] = "xq_a_token=token"
    session = FakeSession(
        [
            FakeResponse("home", content_type="text/html"),
            FakeResponse(
                "{}",
                content_type="application/json",
                status_code=400,
                json_value={"error_code": "10022"},
            ),
        ],
        {"xq_a_token": "token"},
    )

    assert not watchdog.refresh(config, session=session, output=output)
    assert output.read_text(encoding="utf-8") == "old cookies"


def test_seed_cookie_auth_probe_success_publishes(tmp_path):
    config = target()
    config["seed_cookie"] = "xq_a_token=token"
    session = FakeSession(
        [
            FakeResponse("home", content_type="text/html"),
            FakeResponse(
                "{}",
                content_type="application/json",
                json_value={"rebalancing": []},
            ),
        ],
        {"xq_a_token": "token"},
    )

    assert watchdog.refresh(config, session=session, output=tmp_path / "out.json")
    assert session.calls[1][0] == watchdog.AUTH_PROBE_URL
    assert (tmp_path / "out.json").exists()


def test_refresh_reads_latest_seed_cookie_file(tmp_path, monkeypatch):
    seed_file = tmp_path / "seed.cookie"
    seed_file.write_text("xq_a_token=latest", encoding="utf-8")
    monkeypatch.setattr(watchdog, "SEED_COOKIE_FILE", seed_file)
    session = FakeSession([
        FakeResponse("homepage", content_type="text/html"),
        FakeResponse("{}", content_type="application/json", json_value={"statuses": []}),
    ], {"xq_a_token": "latest"})

    assert watchdog.refresh(target(), session=session, output=tmp_path / "out.json")
    assert session.cookies.set_calls[0][0:2] == ("xq_a_token", "latest")
    saved = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert saved["seed_sha256"]


def test_seed_cookie_auth_probe_business_error_still_publishes(tmp_path):
    # 组合不存在（20809）等业务错误同样证明登录会话有效，应通过并发布。
    config = target()
    config["seed_cookie"] = "xq_a_token=token"
    session = FakeSession(
        [
            FakeResponse("home", content_type="text/html"),
            FakeResponse(
                "{}",
                content_type="application/json",
                status_code=400,
                json_value={"error_code": "20809", "error_description": "该组合不存在"},
            ),
        ],
        {"xq_a_token": "token"},
    )

    assert watchdog.refresh(config, session=session, output=tmp_path / "out.json")


def test_seed_cookie_injects_values_into_session(tmp_path):
    session = FakeSession(
        [
            FakeResponse("home", content_type="text/html"),
            FakeResponse("{}", content_type="application/json", json_value={"statuses": []}),
        ]
    )
    config = target()
    config["seed_cookie"] = "xq_a_token=token; u=42; ignored"

    assert watchdog.refresh(config, session=session, output=tmp_path / "out.json")
    assert session.cookies.set_calls == [
        ("xq_a_token", "token", {"domain": ".xueqiu.com", "path": "/"}),
        ("u", "42", {"domain": ".xueqiu.com", "path": "/"}),
    ]


def test_unchallenged_homepage_still_requires_probe(tmp_path):
    output = tmp_path / "waf_cookies.json"
    write_old(output)
    session = FakeSession(
        [
            FakeResponse("homepage", content_type="text/html"),
            FakeResponse("{}", content_type="application/json", json_value={"statuses": []}),
        ],
        {"xq_a_token": "token"},
    )

    assert watchdog.refresh(
        target(),
        session=session,
        solve=lambda html, url: (_ for _ in ()).throw(AssertionError("solver should not run")),
        output=output,
    )
    assert output.exists()


@pytest.mark.parametrize("probe_json", [{}, {"statuses": {}}, [], {"statuses": None}])
def test_probe_requires_list_valued_statuses(tmp_path, probe_json):
    output = tmp_path / "waf_cookies.json"
    write_old(output)
    session = FakeSession(
        [
            FakeResponse("homepage", content_type="text/html"),
            FakeResponse("json", content_type="application/json", json_value=probe_json),
        ],
        {"xq_a_token": "token"},
    )

    assert not watchdog.refresh(target(), session=session, output=output)
    assert output.read_text(encoding="utf-8") == "old cookies"
