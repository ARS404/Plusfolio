from django.apps import AppConfig


class CoreConfig(AppConfig):
    name='core'
    default_auto_field='django.db.models.BigAutoField'

    def ready(self):
        from django.db.models.signals import post_save,post_delete
        from .models import Problem,Circle,Worksheet,Topic,CatalogueSearchDocument
        from .search import sync_problem
        from .catalogue_search import sync_entity,sync_topics
        def changed(sender,instance,raw=False,**kwargs):
            if raw:return
            if sender is Problem:sync_problem(instance)
            elif sender is Topic:
                sync_entity(instance) if kwargs.get('created') else sync_topics()
            else:sync_entity(instance)
        def removed(sender,instance,**kwargs):
            CatalogueSearchDocument.objects.filter(kind=instance._meta.model_name,object_id=instance.pk).delete()
        for model in [Problem,Circle,Worksheet,Topic]:
            post_save.connect(changed,sender=model,weak=False,dispatch_uid='search-'+model._meta.model_name)
        for model in [Circle,Worksheet,Topic]:
            post_delete.connect(removed,sender=model,weak=False,dispatch_uid='search-delete-'+model._meta.model_name)
