import httpx

from app.weibo_qr import create_qr, poll_qr


def test_create_qr_parses_jsonp():
    def handler(request):
        return httpx.Response(
            200,
            text=(
                'window.CB && CB({"retcode":20000000,'
                '"data":{"qrid":"Q1","image":"//qr.example/q.png"}});'
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    c, qrid, url = create_qr(client)
    assert c is client and qrid == "Q1" and url == "https://qr.example/q.png"


def test_poll_qr_pending_then_ok():
    calls = {"n": 0}

    def handler(request):
        path = request.url.path
        if "qrcode/check" in path:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(
                    200, text='window.CB && CB({"retcode":50114001,"data":null});'
                )
            return httpx.Response(
                200,
                text='window.CB && CB({"retcode":20000000,"data":{"alt":"ALT"}});',
            )
        if "login.php" in path:
            return httpx.Response(
                200,
                text=(
                    'window.CB && CB({"crossDomainUrlList":'
                    '["http://passport.weibo.com/sso/crossdomain"]});'
                ),
            )
        if "passport.weibo.com" in str(request.url):
            return httpx.Response(
                200,
                text="ok",
                headers={"set-cookie": "SUB=s1; Path=/; Domain=.weibo.com"},
            )
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert poll_qr(client, "Q1")["status"] == "pending"
    result = poll_qr(client, "Q1")
    assert result["status"] == "ok" and "SUB=s1" in result["cookie"]
