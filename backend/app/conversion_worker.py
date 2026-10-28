"""Isolated native conversion process. Stdout is machine-readable metadata only."""
import json
import sys
import contextlib
import io
from pathlib import Path


def main():
    if sys.platform.startswith('linux'):
        import resource
        resource.setrlimit(resource.RLIMIT_AS,(1536*1024**2,1536*1024**2))
        resource.setrlimit(resource.RLIMIT_CPU,(110,110))
        resource.setrlimit(resource.RLIMIT_FSIZE,(150*1024**2,150*1024**2))
    from .conversion import convert, ConversionSettings, ConversionError
    try:
        root=Path(sys.argv[1]);spec=json.loads((root/'request.json').read_text())
        paths=[]
        for filename in spec['inputs']:
            if Path(filename).name!=filename: raise ConversionError('Invalid input path.','invalid_file')
            paths.append(root/'inputs'/filename)
        # Sandboxed office engines need source files bound inside their work dir.
        work=root/'outputs'
        copied=None
        if spec['source'] in ('pptx','xlsx','doc','docx') and spec['target']=='pdf' and not spec.get('inspection_only'):
            import shutil
            copied=work/paths[0].name;shutil.copyfile(paths[0],copied);paths=[copied]
        # Third-party layout helpers print notices. Keep stdout protocol-clean
        # and discard incidental diagnostics rather than logging document data.
        with contextlib.redirect_stdout(io.StringIO()):
            if spec.get('inspection_only'):
                from .document_tools import inspect_inputs
                result={'inspection':inspect_inputs(paths,spec['formats'])}
            elif spec.get('operation'):
                from .document_tools import operate,ToolSettings
                result=operate(paths,spec['formats'],spec['operation'],work,ToolSettings.model_validate(spec['settings']))
            else:
                result=convert(paths,spec['source'],spec['target'],work,ConversionSettings.model_validate(spec['settings']))
        if copied:copied.unlink(missing_ok=True)
        print(json.dumps(result))
    except ConversionError as exc:
        print(json.dumps({'error':str(exc),'error_code':exc.code}));sys.exit(2)
    except OSError as exc:
        message='Not enough disk space for conversion.' if exc.errno==28 else 'File processing failed. Upload a fresh document or retry later.'
        print(json.dumps({'error':message,'error_code':'storage_failed'}));sys.exit(2)
    except Exception:
        print(json.dumps({'error':'The document is corrupted, malformed or cannot be converted safely. Try re-exporting it.','error_code':'invalid_document'}));sys.exit(2)


if __name__=='__main__': main()
