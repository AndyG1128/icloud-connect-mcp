#!/usr/bin/env python3
"""Build local review artifacts only; no uploading, tagging or remote access."""
import os
from pathlib import Path
import json
import gzip
import io
import tarfile
from setuptools.build_meta import build_wheel, build_sdist

root=Path(__file__).resolve().parents[1]
os.chdir(root)
evidence=json.loads((root/'docs/release-baseline.json').read_text())
os.environ.setdefault('SOURCE_DATE_EPOCH',str(evidence['source_date_epoch']))
output=root/'dist';output.mkdir(exist_ok=True)
build_wheel(str(output))
archive=output/build_sdist(str(output))
# Normalize archive metadata, preserving file contents and executable scripts.
epoch=int(os.environ['SOURCE_DATE_EPOCH'])
normalized=io.BytesIO()
with tarfile.open(archive,'r:gz') as source, tarfile.open(fileobj=normalized,mode='w',format=tarfile.PAX_FORMAT) as target:
    for member in sorted(source.getmembers(),key=lambda entry:entry.name):
        member.uid=member.gid=0
        member.uname=member.gname=''
        member.mtime=epoch
        member.pax_headers={}
        member.mode=0o755 if member.isdir() or member.mode & 0o111 else 0o644
        target.addfile(member,source.extractfile(member) if member.isfile() else None)
with archive.open('wb') as file:
    with gzip.GzipFile(filename='',mode='wb',fileobj=file,mtime=epoch) as compressed:
        compressed.write(normalized.getvalue())
