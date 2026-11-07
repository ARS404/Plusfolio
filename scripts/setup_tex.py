#!/usr/bin/env python3
"""Install pinned official Tectonic and warm trusted template/TikZ resources, never user data."""
import argparse, hashlib, json, os, platform, shutil, subprocess, sys, tarfile, tempfile, time
from pathlib import Path
from download_asset import download
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from core.tex_resources import record_preparation,resource_files
from core.tex_runtime import job_directory
VERSION='0.17.0'
ASSETS={
 ('Darwin','arm64'):('aarch64-apple-darwin','a3f1cac7c5678f01661a92212f58480ae3b0634115d880dbc59e2953ded45667'),
 ('Linux','x86_64'):('x86_64-unknown-linux-musl','8533d07f9ccbd7a65824b9e0459041bca34af1eb33daba48f59215593753a3b7'),
 ('Linux','aarch64'):('aarch64-unknown-linux-musl','b10954a95404f3ab2328d2fa59a5ebab8e657f893fab096f98be8db7c0c979b8'),
}


def install_compiler(asset,binary,digest):
 with asset.open('rb') as source:
  if hashlib.file_digest(source,'sha256').hexdigest()!=digest:raise RuntimeError('Tectonic checksum mismatch')
 temporary=None
 try:
  with tarfile.open(asset,mode='r:gz') as archive:
   members=[member for member in archive.getmembers() if member.isfile() and Path(member.name).name=='tectonic']
   if len(members)!=1:raise RuntimeError('Unexpected release archive')
   with archive.extractfile(members[0]) as source,tempfile.NamedTemporaryFile(prefix='.tectonic-',dir=binary.parent,delete=False) as target:
    temporary=Path(target.name);shutil.copyfileobj(source,target)
  temporary.chmod(0o755);temporary.replace(binary)
 finally:
  if temporary is not None:temporary.unlink(missing_ok=True)


def copy_resources(source,destination):
 """Replace resources from regular files, retaining the old cache on ordinary failure.

 Snapshot jobs stay on the destination filesystem and use leases so later setup
 calls can reclaim interrupted copies without deleting another active setup.
 The two renames are not an atomic exchange: SIGKILL between them requires a rerun.
 """
 files=resource_files(source)  # Check count/bytes before allocating a snapshot or copying data.
 destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
 with job_directory(destination.parent/'.tex-resource-jobs') as directory:
  snapshot=directory/'cache';snapshot.mkdir()
  previous=directory/'previous'
  for name,path in files.items():
   target=snapshot/name;target.parent.mkdir(parents=True,exist_ok=True)
   shutil.copy2(path,target,follow_symlinks=False)
   if target.is_symlink():raise ValueError('TeX resource changed while copying')
  had_previous=destination.exists() or destination.is_symlink()
  try:
   if had_previous:destination.replace(previous)
   snapshot.replace(destination)
  except BaseException:
   if previous.exists() or previous.is_symlink():previous.replace(destination)
   raise


def main(argv=None):
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--offline',action='store_true',help='Validate bundled resources in a temporary copy; never download or modify them.')
 args=parser.parse_args(argv)
 target,digest=ASSETS[(platform.system(),platform.machine())]
 tools=ROOT/'.local/tools';tools.mkdir(parents=True,exist_ok=True);binary=tools/'tectonic'
 if not binary.exists():
  url=f'https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40{VERSION}/tectonic-{VERSION}-{target}.tar.gz'
  print('Downloading official Tectonic '+VERSION,flush=True)
  with tempfile.TemporaryDirectory(prefix='tectonic-download-') as directory:
   asset=Path(directory)/'tectonic.tar.gz';download(url,asset,digest,workers=8)
   install_compiler(asset,binary,digest)
 version=subprocess.check_output([str(binary),'--version'],text=True).strip()
 if not version.startswith('Tectonic '+VERSION) and not version.startswith('tectonic '+VERSION):raise RuntimeError('Unexpected Tectonic version')
 frozen_cache=ROOT/'.local/tectonic-cache'
 cache=Path(os.environ.get('PLUSFOLIO_TEX_SHARED_CACHE',str(frozen_cache)));config=ROOT/'.local/tectonic-config'
 cache.mkdir(parents=True,exist_ok=True);config.mkdir(exist_ok=True)
 if args.offline:
  with job_directory(ROOT/'.local/tex-setup-jobs') as directory:
   isolated=directory/'cache';copy_resources(frozen_cache,isolated)
   prepare_templates(binary,isolated,config,offline=True)
 else:
  prepare_templates(binary,cache,config)
  if cache.resolve()!=frozen_cache.resolve():copy_resources(cache,frozen_cache)
  record_preparation(ROOT,frozen_cache)
 total=sum(path.stat().st_size for path in frozen_cache.rglob('*') if path.is_file())
 print(json.dumps({'compiler':version,'binary_mib':round(binary.stat().st_size/1024**2,1),'cache_mib':round(total/1024**2,1),'offline_check':'passed'},ensure_ascii=False))


def prepare_templates(binary,cache,config,*,offline=False):
 """Warm fixed trusted examples and validate both templates in a leased workspace."""
 env={'PATH':'/usr/bin:/bin','LANG':'en_US.UTF-8','TECTONIC_CACHE_DIR':str(cache),'XDG_CONFIG_HOME':str(config),'TECTONIC_UNTRUSTED_MODE':'1'}
 with job_directory(ROOT/'.local/tex-setup-jobs') as work:
  template=(ROOT/'backend/core/tex_templates/math-a4-v2.tex').read_text()
  (work/'main.tex').write_text(r'\input{variables.tex}\input{template.tex}')
  (work/'template.tex').write_text(template)
  (work/'variables.tex').write_text('\n'.join(r'\newcommand{\Plusfolio'+key+'}{'+value+'}' for key,value in {'Circle':'Plusfolio','Date':'22.10.2026','Title':'Проверка TeX и TikZ','Number':'1','Description':'Только демонстрационные данные.'}.items()))
  (work/'problems.tex').write_text(r'\begin{enumerate}\item Вычислите $\sum_{k=1}^{10} k$ и $\frac{\sqrt{2}}{3}$.\item Проверьте $\mathbb{N}\subset\mathbb{R}\subset\mathbb{C}$, $\varnothing$, $\square$, $\blacksquare$, $\leqslant$, $\mathfrak{g}$. {\footnotesize $\mathbb{Z}\cup\mathbb{Q}$, $\square$ и $x^{\mathbb{N}}$.}\item \begin{tikzpicture}\coordinate (A) at (0,0);\coordinate (B) at (3,0);\coordinate (C) at (1,2);\draw[thick] (A)--(B)--(C)--cycle;\node[below] at (A) {$A$};\node[below] at (B) {$B$};\node[above] at (C) {$C$};\end{tikzpicture}\end{enumerate}')
  with (work/'problems.tex').open('a') as sample:
   sample.write(r'\begin{definition}[Инвариант]Величина сохраняется.\end{definition}\begin{theorem}Утверждение.\end{theorem}\begin{lemma}Лемма.\end{lemma}\begin{example}Пример.\end{example}\begin{remark}Замечание.\end{remark}')
   for size in ['normalsize','small','footnotesize','scriptsize','tiny','Large']:
    sample.write('{\\'+size+r' $x_{i_j}^{a_b}+\sqrt{\frac{x^2}{1+a_{b_c}}}+\mathbb{R}_{x_{y_z}}+\mathfrak{g}+\mathcal{A}+\square+\boldsymbol{\alpha_{i_j}}$}'+chr(10))
  (work/'solutions.tex').write_text(r'\section*{Решения}Ответ: $55$.')
  print('Warming the trusted template, Russian fonts and TikZ bundle cache...',flush=True)
  ready=subprocess.run([str(binary),'-X','compile','--untrusted','--only-cached','main.tex'],cwd=work,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT,timeout=60).returncode==0
  if offline and not ready:
   raise RuntimeError('Bundled offline TeX resources are incomplete. Ask the administrator to run scripts/setup_tex.py and rebuild the toolchain archive; do not update the downloaded manifest.')
  for attempt in range(0 if ready else 3):
   try:
    subprocess.run([str(binary),'-X','compile','--untrusted','main.tex'],cwd=work,env=env,check=True,timeout=600)
    break
   except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
    if attempt==2:raise
    print('Retrying trusted bundle preparation; already downloaded resources are retained.',flush=True)
    time.sleep(2**attempt)
  if not ready:
   subprocess.run([str(binary),'-X','compile','--untrusted','--only-cached','main.tex'],cwd=work,env=env,check=True,timeout=30)
  (work/'template.tex').write_text((ROOT/'backend/core/tex_templates/math-a4-v1.tex').read_text())
  (work/'problems.tex').write_text(r'\begin{enumerate}\item Старый шаблон: $2+2=4$.\end{enumerate}')
  subprocess.run([str(binary),'-X','compile','--untrusted','--only-cached','main.tex'],cwd=work,env=env,check=True,timeout=30)

if __name__=='__main__':main()
