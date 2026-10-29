"""Lean Chromium DevTools PDF rendering for Vercel's limited ephemeral disk.

Uses the same canonical HTML, embedded fonts, browser pagination and print engine
as the local Playwright renderer. CDP avoids bundling Playwright's 142 MB Node
runtime, leaving room for a real Chromium executable and its graphics libraries.
"""
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time

import httpx
import pymupdf
import websocket


class Protocol:
    def __init__(self,url):
        self.connection=websocket.create_connection(url,timeout=15,suppress_origin=True)
        self.sequence=0
        self.deadline=time.monotonic()+50

    def send(self,method,params=None):
        self.sequence+=1;key=self.sequence
        self.connection.send(json.dumps({'id':key,'method':method,'params':params or {}}))
        while True:
            remaining=self.deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('PDF renderer time limit exceeded')
            self.connection.settimeout(min(remaining,25))
            event=json.loads(self.connection.recv())
            if event.get('id')!=key:continue
            if 'error' in event:raise RuntimeError('Chromium command failed: '+method)
            return event.get('result',{})

    def evaluate(self,expression):
        result=self.send('Runtime.evaluate',{'expression':expression,'returnByValue':True})
        if result.get('exceptionDetails'):raise ValueError('Document pagination raised an error')
        return result.get('result',{}).get('value')

    def close(self):self.connection.close()


def render(content,executable=None):
    from .document_renderer import render_document,missing_text_tokens
    from .lambda_chromium import prepare,ARGS
    executable=executable or prepare()
    with tempfile.TemporaryDirectory(prefix='formiqo-pdf-') as directory:
        root=Path(directory)
        source=root/'resume.html';source.write_text(render_document(content,embed_fonts=True)['html'])
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
        flags=ARGS if os.name!='nt' and 'formiqo-chromium' in str(executable) else ['--headless','--disable-dev-shm-usage','--disable-background-networking','--no-sandbox']
        command=[executable,*flags,'--remote-debugging-address=127.0.0.1','--remote-debugging-port='+str(port),'--user-data-dir='+str(root/'profile'),'about:blank']
        stderr=tempfile.TemporaryFile()
        process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=stderr,env=dict(os.environ))
        protocol=None
        try:
            with httpx.Client(trust_env=False,timeout=3) as client:
                deadline=time.monotonic()+15;target=None
                while time.monotonic()<deadline:
                    if process.poll() is not None:
                        stderr.seek(0);message=stderr.read()[-2000:].decode(errors='replace')
                        import logging
                        logging.getLogger('formiqo').error('pdf_chromium_exited code=%s diagnostics=%s',process.returncode,message)
                        raise RuntimeError('Chromium did not start')
                    try:
                        targets=client.get(f'http://127.0.0.1:{port}/json/list').json()
                        target=next((item for item in targets if item.get('type')=='page'),None)
                        if target:break
                    except (httpx.HTTPError,ValueError):pass
                    time.sleep(.1)
                if not target:raise TimeoutError('Chromium startup timed out')
            protocol=Protocol(target['webSocketDebuggerUrl'])
            protocol.send('Page.enable');protocol.send('Network.enable')
            # Block network access before navigating to the sanitized local document.
            protocol.send('Network.setBlockedURLs',{'urls':['http://*','https://*','ftp://*']})
            protocol.send('Emulation.setDeviceMetricsOverride',{'width':850,'height':1200,'deviceScaleFactor':1,'mobile':False})
            protocol.send('Page.navigate',{'url':source.as_uri()})
            while time.monotonic()<protocol.deadline:
                failure=protocol.evaluate('window.__FORMIQO_ERROR__ || null')
                if failure:raise ValueError('Document geometry could not be paginated')
                if protocol.evaluate('window.__FORMIQO_READY__ === true'):break
                time.sleep(.1)
            else:raise TimeoutError('Document fonts or pagination did not finish')
            info=protocol.evaluate('window.__FORMIQO_RESULT__')
            info['fit']=protocol.evaluate('window.__FORMIQO_FIT__ || null')
            output=protocol.send('Page.printToPDF',{'printBackground':True,'preferCSSPageSize':True,'generateTaggedPDF':True,'transferMode':'ReturnAsBase64'})
            data=base64.b64decode(output['data'])
            with pymupdf.open(stream=data,filetype='pdf') as pdf:
                if len(pdf)!=info['pages']:raise ValueError('Rendered page count does not match the canvas')
                text=' '.join(page.get_text() for page in pdf)
                if not text.strip():raise ValueError('Generated PDF has no selectable text')
                if missing_text_tokens(content.text(),text):raise ValueError('PDF text coverage could not verify every source token')
            info['text_coverage']=100
            return data,info
        finally:
            if protocol:protocol.close()
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            stderr.close()
