"""Unpack the build-pinned Lambda Chromium assets for actual HTML/PDF rendering.

Not a ReportLab look-alike or screenshot export: the same document HTML and
pagination code runs in real Chromium on Vercel. No runtime binary URL is fetched.
"""
from pathlib import Path
import io
import os
import threading
import tarfile
import tempfile

_lock=threading.Lock()
_executable=None
ASSETS=Path(__file__).parent/'runtime_assets'/'chromium'/'bin'


def prepare():
    global _executable
    import brotli
    root=Path(tempfile.gettempdir())/'formiqo-chromium'
    with _lock:
        if _executable:return _executable
        import logging,shutil
        logging.getLogger('formiqo').info('pdf_runtime_cache_free_mb=%s',round(shutil.disk_usage(tempfile.gettempdir()).free/1024**2))
        root.mkdir(parents=True,exist_ok=True)
        executable=root/'chromium'
        if not executable.is_file():
            for name,destination in [('al2023.tar.br',root/'al2023'),('fonts.tar.br',root/'fonts'),('swiftshader.tar.br',root)]:
                destination.mkdir(parents=True,exist_ok=True)
                packed=ASSETS/name
                with tarfile.open(fileobj=io.BytesIO(brotli.decompress(packed.read_bytes())),mode='r:') as archive:
                    archive.extractall(destination,filter='data')
            # The lean CDP runtime leaves room for the real executable and adjacent
            # graphics libraries; Chromium discovers its resource directory normally.
            temporary=root/'chromium.unpacking'
            decoder=brotli.Decompressor()
            with (ASSETS/'chromium.br').open('rb') as source,temporary.open('wb') as target:
                while chunk:=source.read(2**20):target.write(decoder.process(chunk))
            temporary.chmod(0o700);temporary.replace(executable)
        lib=str(root/'al2023'/'lib')
        os.environ['LD_LIBRARY_PATH']=str(root)+':'+lib+':'+os.environ.get('LD_LIBRARY_PATH','')
        os.environ['VK_ICD_FILENAMES']=str(root/'vk_swiftshader_icd.json')
        os.environ['FONTCONFIG_PATH']=str(root/'fonts')
        os.environ.setdefault('HOME','/tmp')
        _executable=str(executable)
    return _executable


ARGS=['--no-sandbox','--disable-setuid-sandbox','--no-zygote','--single-process',
      '--disable-dev-shm-usage','--disable-background-networking',
      '--ignore-gpu-blocklist','--in-process-gpu','--use-gl=angle','--use-angle=swiftshader',
      '--enable-unsafe-swiftshader','--font-render-hinting=none','--disable-features=AudioServiceOutOfProcess,IsolateOrigins,site-per-process']
