"""Package requested source, calculated results and reports for GitHub upload."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import json

ROOT = Path(__file__).resolve().parent


def selected_files():
    files = [p for p in ROOT.iterdir() if p.is_file() and
             (p.suffix in ('.py', '.md') or p.name in ('.gitignore', 'requirements.txt'))]
    files += [p for p in (ROOT / 'output').rglob('*') if p.is_file() and
              p.suffix.lower() in ('.txt', '.csv', '.json', '.html', '.pdf')]
    files += [ROOT / 'reference_data' / n for n in ('download_receipt.json', 'rinex4_coverage_check.json')]
    return sorted([p for p in files if p.exists()], key=lambda p: p.relative_to(ROOT).as_posix())


if __name__ == '__main__':
    files = selected_files()
    records = [dict(path=p.relative_to(ROOT).as_posix(), bytes=p.stat().st_size,
                    sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in files]
    archive = ROOT.parent / 'spoof_detec_upload.zip'
    with ZipFile(archive, 'w', ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.relative_to(ROOT).as_posix())
        z.writestr('UPLOAD_MANIFEST.json', json.dumps(records, indent=2, ensure_ascii=False))
    with ZipFile(archive) as z:
        if z.testzip() is not None:
            raise RuntimeError('Archive verification failed')
    print(json.dumps(dict(archive=str(archive), files=len(files), bytes=archive.stat().st_size), indent=2))
