#!/usr/bin/env python3
"""Install pinned official Tectonic and warm trusted template/TikZ resources, never user data."""
import hashlib,io,json,os,platform,subprocess,sys,tarfile,tempfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VERSION='0.17.0'
ASSETS={
 ('Darwin','arm64'):('aarch64-apple-darwin','a3f1cac7c5678f01661a92212f58480ae3b0634115d880dbc59e2953ded45667'),
 ('Linux','x86_64'):('x86_64-unknown-linux-musl','8533d07f9ccbd7a65824b9e0459041bca34af1eb33daba48f59215593753a3b7'),
 ('Linux','aarch64'):('aarch64-unknown-linux-musl','b10954a95404f3ab2328d2fa59a5ebab8e657f893fab096f98be8db7c0c979b8'),
}

def main():
 target,digest=ASSETS[(platform.system(),platform.machine())]
 tools=ROOT/'.local/tools';tools.mkdir(parents=True,exist_ok=True);binary=tools/'tectonic'
 if not binary.exists():
  url=f'https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40{VERSION}/tectonic-{VERSION}-{target}.tar.gz'
  print('Downloading official Tectonic '+VERSION,flush=True)
  with urllib.request.urlopen(url,timeout=60) as response:payload=response.read()
  if hashlib.sha256(payload).hexdigest()!=digest:raise RuntimeError('Tectonic checksum mismatch')
  with tarfile.open(fileobj=io.BytesIO(payload),mode='r:gz') as archive:
   members=[member for member in archive.getmembers() if member.isfile() and Path(member.name).name=='tectonic']
   if len(members)!=1:raise RuntimeError('Unexpected release archive')
   binary.write_bytes(archive.extractfile(members[0]).read());binary.chmod(0o755)
 version=subprocess.check_output([str(binary),'--version'],text=True).strip()
 if not version.startswith('Tectonic '+VERSION) and not version.startswith('tectonic '+VERSION):raise RuntimeError('Unexpected Tectonic version')
 cache=ROOT/'.local/tectonic-cache';config=ROOT/'.local/tectonic-config'
 cache.mkdir(exist_ok=True);config.mkdir(exist_ok=True)
 env={'PATH':'/usr/bin:/bin','LANG':'en_US.UTF-8','TECTONIC_CACHE_DIR':str(cache),'XDG_CONFIG_HOME':str(config),'TECTONIC_UNTRUSTED_MODE':'1'}
 with tempfile.TemporaryDirectory(prefix='plusfolio-tex-setup-') as directory:
  work=Path(directory)
  template=(ROOT/'backend/core/tex_templates/math-a4-v1.tex').read_text()
  (work/'main.tex').write_text(r'\input{variables.tex}\input{template.tex}')
  (work/'template.tex').write_text(template)
  (work/'variables.tex').write_text('\n'.join(r'\newcommand{\Plusfolio'+key+'}{'+value+'}' for key,value in {'Circle':'Plusfolio','Date':'22.10.2026','Title':'Проверка TeX и TikZ','Number':'1','Description':'Только демонстрационные данные.'}.items()))
  (work/'problems.tex').write_text(r'\begin{enumerate}\item Вычислите $\sum_{k=1}^{10} k$ и $\frac{\sqrt{2}}{3}$.\item Проверьте $\mathbb{N}\subset\mathbb{R}\subset\mathbb{C}$, $\varnothing$, $\square$, $\blacksquare$, $\leqslant$, $\mathfrak{g}$. {\footnotesize $\mathbb{Z}\cup\mathbb{Q}$, $\square$ и $x^{\mathbb{N}}$.}\item \begin{tikzpicture}\coordinate (A) at (0,0);\coordinate (B) at (3,0);\coordinate (C) at (1,2);\draw[thick] (A)--(B)--(C)--cycle;\node[below] at (A) {$A$};\node[below] at (B) {$B$};\node[above] at (C) {$C$};\end{tikzpicture}\end{enumerate}')
  with (work/'problems.tex').open('a') as sample:
   for size in ['normalsize','small','footnotesize','scriptsize','tiny','Large']:
    sample.write('{\\'+size+r' $x_{i_j}^{a_b}+\sqrt{\frac{x^2}{1+a_{b_c}}}+\mathbb{R}_{x_{y_z}}+\mathfrak{g}+\mathcal{A}+\square+\boldsymbol{\alpha_{i_j}}$}'+chr(10))
  (work/'solutions.tex').write_text(r'\section*{Решения}Ответ: $55$.')
  print('Warming the trusted template, Russian fonts and TikZ bundle cache...',flush=True)
  subprocess.run([str(binary),'-X','compile','--untrusted','main.tex'],cwd=work,env=env,check=True,timeout=600)
  subprocess.run([str(binary),'-X','compile','--untrusted','--only-cached','main.tex'],cwd=work,env=env,check=True,timeout=30)
 total=sum(path.stat().st_size for path in cache.rglob('*') if path.is_file())
 print(json.dumps({'compiler':version,'binary_mib':round(binary.stat().st_size/1024**2,1),'cache_mib':round(total/1024**2,1),'offline_check':'passed'},ensure_ascii=False))

if __name__=='__main__':main()
