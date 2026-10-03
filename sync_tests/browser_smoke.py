"""Optional real-browser smoke against the synthetic owner/gateway only."""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from pathlib import Path


def run_browser_smoke(gateway_url, init_data, client, headers):
    from playwright.sync_api import sync_playwright

    dist = Path(__file__).resolve().parents[1] / 'miniapp' / 'dist'
    if not dist.is_dir():
        raise RuntimeError('Build the miniapp before running browser smoke')

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(dist)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 390, 'height': 844})
            context.add_init_script("""window.Telegram={WebApp:{initData: %s, themeParams:{}, colorScheme:'light', ready(){}, expand(){}, onEvent(){}, offEvent(){}, BackButton:{show(){},hide(){},onClick(){},offClick(){}}}};""" % json.dumps(init_data))
            context.route('https://telegram.org/**', lambda route: route.abort())

            def relay(route):
                request = route.request
                response = client.request(request.method, gateway_url + request.url.split('8000', 1)[1],
                                          headers={key: value for key, value in request.headers.items() if key.lower() not in {'host', 'origin', 'content-length'}},
                                          content=request.post_data_buffer)
                route.fulfill(status=response.status_code, body=response.content,
                              headers={'Content-Type': response.headers.get('content-type', 'application/json'),
                                       'Access-Control-Allow-Origin': base, 'Access-Control-Allow-Headers': 'Authorization, Content-Type'})

            context.route('http://localhost:8000/**', relay)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/#/histology/exam')
            page.get_by_role('button', name='Практический зачёт').click()
            page.get_by_role('button', name='Показать ответ').click()
            before = client.get(gateway_url+'/api/v1/histology/exam/stats', headers=headers).json()['attempts']
            page.get_by_role('button', name='Узнал', exact=True).evaluate('(button) => {button.click(); button.click();}')
            page.get_by_role('button', name='Показать ответ').wait_for()
            after = client.get(gateway_url+'/api/v1/histology/exam/stats', headers=headers).json()['attempts']
            assert after == before + 1, (before, after)
            page.goto(base + '/#/tests/anatomy')
            page.get_by_role('button', name=__import__('re').compile('Продолжить ·')).click()
            page.get_by_role('radio').first.click()
            page.get_by_role('button', name='Следующий вопрос').wait_for()
            page.reload()
            page.get_by_role('button', name=__import__('re').compile('Продолжить ·')).click()
            active = client.get(gateway_url+'/api/v1/anatomy/exam/runs/active', headers=headers).json()
            assert active['answered'] == 2, active
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    return {'browser_histology_duplicate_click': True, 'browser_anatomy_resume': True, 'browser_runtime_errors': []}
