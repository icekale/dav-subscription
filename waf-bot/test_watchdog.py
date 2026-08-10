import json

import pytest
import watchdog


class FakeCookies:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.set_calls = []

    def set(self, name, value, **kwargs):
        self.set_calls.append((name, value, kwargs))
        self.values[name] = value

    def get_dict(self):
        return dict(self.values)


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


def target(tmp_path):
    return {
        "url": "https://xueqiu.com/",
        "out": "xueqiu",
        "seed_cookie": "",
        "ok_marker": "unused",
        "output": tmp_path / "waf_cookies.json",
    }


def write_old(path):
    path.write_text("old cookies", encoding="utf-8")


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

    assert calls["command"] == ["node", str(watchdog.SOLVER)]
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
    assert watchdog.refresh(target(tmp_path), session=session, solve=solve, output=output)
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
        target(tmp_path),
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

    assert not watchdog.refresh(target(tmp_path), session=session, output=output)
    assert output.read_text(encoding="utf-8") == "old cookies"


def test_seed_cookie_injects_values_into_session(tmp_path):
    session = FakeSession(
        [
            FakeResponse("home", content_type="text/html"),
            FakeResponse("{}", content_type="application/json", json_value={"statuses": []}),
        ]
    )
    config = target(tmp_path)
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
        target(tmp_path),
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

    assert not watchdog.refresh(target(tmp_path), session=session, output=output)
    assert output.read_text(encoding="utf-8") == "old cookies"
