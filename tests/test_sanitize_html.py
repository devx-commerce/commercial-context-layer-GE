from app.sources.mime import sanitize_html


def test_script_and_style_are_stripped():
    html = "<html><body><script>alert(1)</script><style>body{}</style><p>hello</p></body></html>"
    result = sanitize_html(html)
    assert "<script" not in result
    assert "<style" not in result
    assert "hello" in result


def test_remote_images_and_tracking_pixels_are_removed():
    html = '<html><body><img src="https://tracker.example.com/pixel.gif"><p>hi</p></body></html>'
    result = sanitize_html(html)
    assert "<img" not in result
    assert "hi" in result


def test_event_handlers_are_stripped():
    html = '<html><body><p onclick="evil()">click</p></body></html>'
    result = sanitize_html(html)
    assert "onclick" not in result
    assert "click" in result


def test_form_and_iframe_removed():
    html = "<html><body><form><input></form><iframe src='x'></iframe><p>text</p></body></html>"
    result = sanitize_html(html)
    assert "<form" not in result
    assert "<iframe" not in result
    assert "text" in result
