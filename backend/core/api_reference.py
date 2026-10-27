from copy import deepcopy
from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .api_contract import operations_for
from .robot_workflows import mandatory_instructions, POLICY_VERSION
from .api_shapes import DESCRIPTIONS, parameter_description, reachable_schemas, request_schema_for, response_schema_for


def schema_for(user, *, demo=False, read_only=False):
    paths = {}
    for item in operations_for(user, demo=demo, read_only=read_only):
        binary = item['binary']
        media = ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','text/tab-separated-values'] if item['id']=='journalExport' else ['application/pdf'] + (['application/x-tex','application/zip'] if set(user.roles)&{'teacher','admin'} else [])
        if item['id']=='texToolchainArchive':media=['application/zip']
        content = {kind: {'schema':{'type':'string','format':'binary'}} for kind in media} if binary else {'application/json':{'schema':response_schema_for(item['id'])}}
        if item['id'] in {'documentationGet','documentationSection'}:
            content['text/markdown']={'schema':{'type':'string','description':'Markdown-файл руководства при download=markdown.'}}
        parameters=deepcopy(item['parameters'])
        for parameter in parameters:
            parameter['description']=parameter_description(item['id'],parameter)
        operation = {'operationId':item['id'],'summary':item['summary'],
                     'description':item['description'] or DESCRIPTIONS.get(item['id'],'Область данных и возможность изменения повторно проверяются сервером.'),
                     'tags':[item['path'].split('/')[3]], 'parameters':parameters,
                     'responses':{str(item['status']):{'description':'Успешный результат.','content':content},
                        **{str(code):{'description':description,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Error'}}}} for code,description in {
                            400:'Ошибка данных или бизнес-правила: проверьте detail.',401:'Нет действительного токена: он отсутствует, истёк, отозван или пароль изменился.',
                            403:'Операция запрещена ролью, назначением, авторством или режимом токена.',404:'Запись не найдена или недоступна текущему аккаунту.',
                            409:'Конфликт версии или дубль: перечитайте данные перед повтором.',429:'Слишком много попыток: выдержите Retry-After.'}.items()}}}
        if item['public']:
            operation['security'] = []
        if 'response_example' in item:
            operation['responses'][str(item['status'])]['content']['application/json']['example'] = item['response_example']
        if item['body'] is not None:
            operation['requestBody'] = {'required':True,'content':{'application/json':{'schema':request_schema_for(item['id'],item['body']),
                **({'example':item['example']} if item['example'] is not None else {})}}}
        paths.setdefault(item['path'][len('/api/v1'):], {})[item['method'].lower()] = operation
    return {'openapi':'3.1.0','x-plusfolio-mandatory-instructions':{'policy_version':POLICY_VERSION,'documentation_url':'/api/v1/documentation?audience=robot','instructions':mandatory_instructions(user,read_only=read_only)},'info':{'title':'Plusfolio API','version':'1.0.0',
                'description':'Роботы MUST до сценария прочитать обязательные инструкции из GET /api/v1/documentation?audience=robot и соблюдать x-plusfolio-mandatory-instructions. Область схемы соответствует текущим ролям и режиму токена. Для автоматизации используйте Bearer; браузерная сессия сохраняет CSRF-защиту. Схема описывает возможности роли, конкретный кружок и авторство проверяются при запросе.'},
            'servers':[{'url':'/api/v1'}], 'security':[{'BearerAuth':[]}], 'paths':paths,
            'externalDocs':{'description':'Читаемый справочник без отправки запросов.','url':'/#/documentation/api'},
            'components':{'securitySchemes':{'BearerAuth':{'type':'http','scheme':'bearer',
                'description':'Непрозрачный токен из POST /api/v1/auth/token. Это не JWT и не OAuth password flow.'}},
                'schemas':reachable_schemas(paths)}}


@api_view(['GET'])
def openapi(request):
    return Response(schema_for(request.user, demo=settings.DEMO, read_only=bool(getattr(request.auth,'read_only',False))))
