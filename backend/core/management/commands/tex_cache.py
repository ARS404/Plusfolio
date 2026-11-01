import json
from django.conf import settings
from django.core.management.base import BaseCommand
from core.tex_cache import pdf_cache,toolchain_cache


class Command(BaseCommand):
    help='Очистить устаревшие PDF/архивы в пределах лимитов и показать размер ресурсов TeX.'
    def handle(self,*args,**options):
        report={'pdf':pdf_cache().prune(),'toolchains':toolchain_cache().prune()}
        from core.tex_runtime import prune_jobs
        report['abandoned_jobs']=prune_jobs(settings.LOCAL_DIR/'tex-jobs')
        report['abandoned_previews']=prune_jobs(settings.BASE_DIR/'.local/tex-previews')
        resources=settings.LOCAL_DIR/'tectonic-cache'
        sizes=[path.stat().st_size for path in resources.rglob('*') if path.is_file() and not path.is_symlink()]
        report['trusted_resources']={'files':len(sizes),'bytes':sum(sizes),'policy':'read-only during document compilation; never evicted'}
        self.stdout.write(json.dumps(report,ensure_ascii=False,indent=2))
