"""Put the End-to-end tab's CSS and JS into a report page.

Templates mark the places with /*__E2E_CSS__*/ (inside <style>) and /*__E2E_JS__*/ (inside a <script>).
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def assets():
    with open(os.path.join(HERE, "view.css"), encoding="utf-8") as fh:
        css = fh.read()
    with open(os.path.join(HERE, "view.js"), encoding="utf-8") as fh:
        js = fh.read()
    return css, js


def inject(page):
    css, js = assets()
    return page.replace("/*__E2E_CSS__*/", css).replace("/*__E2E_JS__*/", js.replace("</", "<\\/"))
