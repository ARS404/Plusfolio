"""One registry for versioned routes, permission-filtered reference and OpenAPI."""
import re
from .search_contract import SEARCH_BODY, SEARCH_PARAMETERS, SEARCH_DESCRIPTION, SEARCH_EXAMPLE, SEARCH_RESPONSE_EXAMPLE

from .catalogue_search_contract import PARAMETERS as CATALOGUE_PARAMETERS, DESCRIPTION as CATALOGUE_DESCRIPTION

STRING = {'type': 'string'}
UUID = {'type': 'string', 'format': 'uuid'}
INT = {'type': 'integer'}
BOOL = {'type': 'boolean'}
ARRAY_UUID = {'type': 'array', 'items': UUID}
ARRAY_INT = {'type': 'array', 'items': INT}


def obj(properties, required=()):
    return {'type': 'object', 'properties': properties, **({'required': list(required)} if required else {})}


def query(name, description, *, multiple=False, schema=None):
    value = {'name': name, 'in': 'query', 'required': False, 'description': description,
             'schema': schema or STRING}
    if multiple:
        value.update(style='form', explode=True, schema={'type': 'array', 'items': schema or STRING})
    return value


Q = query('q', 'Поиск по публичному ID или тексту. Не более 160 символов.')
TAG = query('tag', 'Числовой ID тега соответствующего справочника.', multiple=True, schema=INT)
TOPIC = query('topic', 'UUID темы. Включает все дочерние темы.', multiple=True, schema=UUID)
CITY = query('city', 'Точное название города. Повторите параметр для нескольких городов.', multiple=True)
ISSUES = query('issues', 'all либо числовые ID выдач через запятую. Например: 12,19.')
SOURCE = [query('solutions', '1 — включить только разрешённые решения.', schema={'enum': ['0', '1']}),
          query('download', '1 — скачать PDF вложением.', schema={'enum': ['0', '1']})]
TOKEN_BODY = obj({'login': {'type': 'string', 'format': 'email'}, 'password': {'type': 'string', 'writeOnly': True},
                  'name': {'type': 'string', 'minLength': 1, 'maxLength': 100},
                  'expires_in_days': {'type': 'integer', 'minimum': 1, 'maximum': 90, 'default': 30},
                  'read_only': {'type': 'boolean', 'default': False}}, ['login', 'password'])
MATERIAL = obj({'title': STRING, 'description': STRING, 'statement': STRING, 'solution': STRING,
                'statement_tex': STRING, 'solution_tex': STRING, 'topics': ARRAY_UUID, 'tags': ARRAY_INT,
                'problems': ARRAY_UUID}, ['topics'])
WORKSHEET_EDIT = obj({'version': INT, 'title': STRING, 'description': STRING,
                      'topics': ARRAY_UUID, 'tags': ARRAY_INT, 'problems': ARRAY_UUID}, ['version'])
MARK = obj({'value': BOOL, 'version': {'type': 'integer', 'minimum': 0}, 'student_id': INT}, ['value', 'version'])


def operation(id, summary, access='all', *, body=None, example=None, parameters=(), status=200, description='', binary=None, public=False):
    return dict(id=id, summary=summary, access=access, body=body, example=example,
                parameters=list(parameters), status=status, description=description, binary=binary, public=public)


# Django converters and view argument names are part of the same registry as the schema.
ROUTES = [
 ('tex/toolchain', 'tex_api.toolchain', {'GET': operation('texToolchain','Получить точный контракт сборки TeX', 'writer',description='До загрузки робот MUST получить contract_id, скачать архив сборки, повторить сборку и согласовать PDF по инструкции robot-tex-build. Операция только читает и доступна токену read_only. Без записей задач или листков.')}),
 ('tex/toolchain/archive', 'tex_api.archive', {'GET': operation('texToolchainArchive','Скачать сборщик, шаблон и подготовленные ресурсы TeX', 'writer',binary=True,description='ZIP содержит точные исходники сборщика сервиса, Tectonic installer с закреплёнными хешами, шаблон, offline-кэш и toolchain-manifest.json. Проверить contract_id и хеши, не использовать другую TeX-сборку. Доступно токену read_only.')}),
 ('catalogue-search','catalogue_search_api.catalogue_search',{'GET':operation('catalogueSearch','Поиск названий и описаний по тексту и смыслу',parameters=CATALOGUE_PARAMETERS,description=CATALOGUE_DESCRIPTION)}),
 ('problem-search', 'search_api.problem_search', {
    'POST': operation('problemSearchText', 'Поиск задач по тексту условия или решения', body=SEARCH_BODY, example=SEARCH_EXAMPLE,
        description='Основной способ: JSON-тело для длинного текста, без передачи условия в URL. '+SEARCH_DESCRIPTION),
    'GET': operation('problemSearch', 'Поиск задач по короткому тексту или ID', parameters=SEARCH_PARAMETERS,
        description='Те же параметры в строке запроса; для полного условия или решения используйте POST, чтобы не упираться в длину URL. '+SEARCH_DESCRIPTION)}),
 ('auth/token', 'automation.token_issue', {'POST': operation('tokenIssue', 'Получить токен по email и паролю', body=TOKEN_BODY,
    example={'login': 'you@example.ru', 'password': '<PASSWORD>', 'name': 'Мой бот', 'expires_in_days': 30, 'read_only': False}, status=201, public=True,
    description='Не создаёт cookie-сессию. Секрет возвращается один раз. По умолчанию 30 суток, максимум 90. Логин — email регистрации. Нужна роль teacher, analyst или admin; аккаунтам только с ролью student API запрещён.')}),
 ('auth/tokens', 'automation.tokens', {
    'GET': operation('tokenList', 'Мои токены без секретов'),
    'POST': operation('tokenCreate', 'Создать ещё один личный токен с проверкой пароля', body=obj({key: value for key,value in TOKEN_BODY['properties'].items() if key != 'login'}, ['password']),
        example={'password': '<CURRENT_PASSWORD>', 'name': 'Выгрузка отчётов', 'expires_in_days': 30, 'read_only': True}, status=201)}),
 ('auth/tokens/current', 'automation.token_revoke', {'DELETE': operation('tokenRevokeCurrent', 'Отозвать текущий Bearer-токен', description='Разрешено также токену только для чтения. Cookie-сессия без Bearer-токена получит 404.')}),
 ('auth/tokens/<uuid:pk>', 'automation.token_revoke', {'DELETE': operation('tokenRevoke', 'Отозвать свой токен по UUID')}),
 ('account', 'api.account', {
    'GET': operation('accountGet', 'Мой профиль, роли и сводка'),
    'PATCH': operation('accountUpdate', 'Изменить свой профиль', body=obj({'name': STRING, 'last_name': STRING, 'first_name': STRING, 'patronymic': STRING, 'graduation_year': INT, 'no_patronymic': BOOL}),
        description='При совмещении со student обязательны last_name, first_name, patronymic, graduation_year и no_patronymic; иначе только name.', example={'name': 'Имя преподавателя'})}),
 ('account/password', 'api.account_password', {'POST': operation('passwordChange', 'Сменить собственный пароль', body=obj({'current_password': STRING, 'new_password': STRING, 'confirm_password': STRING}, ['current_password','new_password','confirm_password']),
    description='Новый пароль от 12 символов. После смены все прежние API-токены становятся недействительными.')}),
 ('circles', 'api.circles', {
    'GET': operation('circleList', 'Доступные кружки', parameters=[Q,CITY]),
    'POST': operation('circleCreate', 'Создать кружок', 'admin', body=obj({'name': STRING, 'city': STRING, 'region': STRING, 'description': STRING, 'tags': ARRAY_INT}, ['name']),
        example={'name':'Математический кружок','city':'Москва','region':'Москва','description':'7–8 классы','tags':[]}, status=201)}),
 ('circles/<uuid:pk>', 'api.circle_detail', {
    'GET': operation('circleGet', 'Данные доступного кружка и флаги возможностей'),
    'PATCH': operation('circleUpdate', 'Изменить свой активный кружок', 'writer', body=obj({'name': STRING,'city': STRING,'region': STRING,'description': STRING,'tags': ARRAY_INT}),
        description='Теги кружка меняет только администратор. can_write зависит от текущего назначения и архива.')}),
 ('circles/<uuid:pk>/members', 'api.members', {
    'GET': operation('memberList', 'Действующие школьники кружка'),
    'POST': operation('memberAdd', 'Зачислить зарегистрированного школьника', 'writer', body=obj({'email': {'type':'string','format':'email'},'student_id': INT}),
        example={'student_id': 12}, description='Укажите либо email, либо числовой student_id из поиска. Автоматически назначаются все прошлые выдачи.'),
    'DELETE': operation('memberRemove', 'Завершить участие школьника', 'writer', body=obj({'email': {'type':'string','format':'email'}}, ['email']), example={'email':'student@example.ru'})}),
 ('circles/<uuid:pk>/student-search', 'api.student_search', {'GET': operation('studentSearch', 'Найти школьника для зачисления', 'writer', parameters=[Q],
    description='ФИО, S-ID или U-ID; число без префикса — ID школьника. До 20 записей с маской email.')}),
 ('circles/<uuid:pk>/members/<int:student_id>', 'api.student_detail', {'PATCH': operation('studentUpdate', 'Исправить год выпуска школьника своего кружка', 'writer',
    body=obj({'graduation_year': {'type':['integer','null'], 'minimum':1900,'maximum':2200}}, ['graduation_year']), example={'graduation_year':2031})}),
 ('circles/<uuid:pk>/teachers', 'api.teachers', {
    'POST': operation('teacherAdd', 'Назначить существующего преподавателя', 'admin', body=obj({'email':STRING}, ['email']), example={'email':'T-3'}, description='Поле email также принимает T-ID или U-ID.'),
    'DELETE': operation('teacherRemove', 'Завершить назначение преподавателя', 'admin', body=obj({'email':STRING}, ['email']), example={'email':'T-3'})}),
 ('circles/<uuid:pk>/issues', 'api.issues', {
    'GET': operation('issueList', 'Выдачи листков кружку', parameters=[Q,TAG,query('mode','hybrid — названия и описания по тексту и смыслу; text — обычный поиск.',schema={'enum':['text','hybrid'],'default':'text'})]),
    'POST': operation('issueCreate', 'Выдать один или несколько листков', 'writer', body=obj({'worksheet_ids':ARRAY_UUID,'issued_on':{'type':'string','format':'date'}}, ['worksheet_ids','issued_on']),
        example={'worksheet_ids':['<REVISION_UUID>'],'issued_on':'2026-10-26'}, description='Массив UUID версий, не document_id. Дата не в будущем. Набор сохраняется атомарно. Ответ — обновлённый список выдач.')}),
 ('circles/<uuid:pk>/issues/<int:issue_id>', 'api.issue_detail', {'GET': operation('issueGet', 'Получить фиксированную выданную версию листка')}),
 ('circles/<uuid:pk>/issues/<int:issue_id>/<str:file_kind>', 'api.issue_document', {'GET': operation('issueFile', 'PDF/TeX/ZIP конкретной выдачи', parameters=SOURCE, binary=True)}),
 ('circles/<uuid:pk>/journal', 'api.journal', {'GET': operation('journalGet', 'Журнал, блоки задач и версии отметок', parameters=[ISSUES,Q])}),
 ('circles/<uuid:pk>/journal/export', 'api.journal_export', {'GET': operation('journalExport', 'Выгрузить текущий срез журнала', parameters=[ISSUES,Q,query('file_format','Формат файла.',schema={'enum':['xlsx','tsv'],'default':'xlsx'})], binary=True)}),
 ('circles/<uuid:pk>/journal/<int:issue_id>', 'api.journal', {'GET': operation('journalIssueGet', 'Журнал одного выданного листка')}),
 ('circles/<uuid:pk>/problems/<uuid:problem_id>/<str:kind>', 'api.mark', {'POST': operation('journalMark', 'Изменить решение, разбор или показ решения', 'writer', body=MARK,
    example={'student_id':12,'value':True,'version':0}, description='kind: solve, discussion или solution-visibility. student_id обязателен только для solve. version возьмите из журнала (0, если записи нет). 409 требует перечитать состояние.')}),
 ('circles/<uuid:pk>/audit', 'api.audit', {'GET': operation('circleAudit', 'История изменений доступного кружка', 'group')}),
 ('materials/<str:kind>', 'api.materials', {
    'GET': operation('materialList', 'Доступные задачи или версии листков', parameters=[Q,TAG,TOPIC,query('scope','Для листков.',schema={'enum':['available','public','mine','all']}),query('pagination','1 — постраничный ответ банка задач.',schema={'enum':['1']}),query('page','Страница банка задач.',schema=INT),query('page_size','Размер страницы банка задач: 1–100.',schema=INT)]),
    'POST': operation('materialCreate', 'Создать неизменяемую задачу или личный листок', 'writer', body=MATERIAL,
        example={'title':'Листок по алгебре','topics':['<TOPIC_UUID>'],'tags':[],'problems':['<PROBLEM_UUID>']},status=201,
        description='kind: problem или worksheet. Для задачи нужны условие и решение текстом или TeX; название необязательно. Для листка нужны название и непустой массив problems без повторов. topics непустой для обоих видов. При загрузке листка робот MUST сначала прочитать /api/v1/documentation/robot-worksheet-upload?audience=robot и соблюдать дополнительные вопросы, выбор аналогов и подтверждение метаданных.')}),
 ('materials/<str:kind>/<uuid:pk>', 'api.material_detail', {'GET': operation('materialGet', 'Условие и разрешённые решения материала', parameters=[query('circle','UUID кружка для контекстного показа решений.',schema=UUID)])}),
 ('materials/<str:kind>/<uuid:pk>/<str:file_kind>', 'api.material_document', {'GET': operation('materialFile', 'Скачать PDF/TeX/ZIP доступного материала', parameters=SOURCE+[query('circle','UUID контекста кружка.',schema=UUID)], binary=True)}),
 ('worksheet-documents/<uuid:pk>', 'api.worksheet_document', {
    'GET': operation('worksheetGet', 'Открыть логический листок по document_id'),
    'PATCH': operation('worksheetUpdate', 'Сохранить новую личную версию своего листка', body=WORKSHEET_EDIT,
        example={'version':1,'title':'Моя редакция','problems':['<PROBLEM_UUID>']}, description='Только автор. version — текущий revision. Не путать document_id с UUID версии id.')}),
 ('worksheet-documents/<uuid:pk>/publish', 'api.worksheet_publish', {'POST': operation('worksheetPublish', 'Опубликовать текущую версию для всех', 'admin', body=obj({'version':INT},['version']), example={'version':2})}),
 ('worksheets/<uuid:pk>/copy', 'api.worksheet_copy', {'POST': operation('worksheetCopy', 'Сохранить себе независимую личную копию', body=obj({}),example={},status=201,
    description='pk — UUID доступной версии. Копия получает новые document_id, W-ID и UUID версии. Доступно также школьнику и аналитику.')}),
 ('my-materials/<str:kind>', 'api.my_materials', {'GET': operation('myMaterials', 'Назначенные мне задачи или листки', 'student', parameters=[Q,TAG], description='kind: problem или worksheet. До 300 записей, уточняйте фильтры.')}),
 ('my-problems/<uuid:pk>', 'api.my_problem', {'GET': operation('myProblem', 'Моя задача с разрешённым решением', 'student')}),
 ('my-issues/<int:issue_id>', 'api.my_issue_detail', {'GET': operation('myIssue', 'Выданный мне листок с параметрами выдачи', 'student')}),
 ('my-issues/<int:issue_id>/<str:file_kind>', 'api.my_issue_document', {'GET': operation('myIssueFile', 'Скачать документ моей выдачи', 'student', parameters=SOURCE, binary=True)}),
 ('topics', 'api.topics', {
    'GET': operation('topicList', 'Темы для выбора и фильтров', parameters=[Q],description='Ответ {topics,version,metadata}; parent_id задаёт дерево, is_other — системную «Прочее».'),
    'POST': operation('topicCreate', 'Создать тему и системную «Прочее»', 'admin', body=obj({'name':STRING,'parent_id':UUID},['name','parent_id']),example={'name':'Многочлены','parent_id':'<PARENT_TOPIC_UUID>'},status=201)}),
 ('topics/<uuid:pk>', 'api.topic_detail', {'PATCH': operation('topicUpdate', 'Переименовать, перенести или архивировать тему', 'admin',body=obj({'name':STRING,'parent_id':UUID,'archived':BOOL}),example={'archived':True})}),
 ('tags', 'api.tags', {
    'GET': operation('tagList', 'Теги всех трёх справочников',parameters=[Q]),
    'POST': operation('tagCreate', 'Создать тег', 'admin',body=obj({'kind':{'enum':['problem','worksheet','circle']},'name':STRING},['kind','name']),example={'kind':'worksheet','name':'Домашняя работа'},status=201)}),
 ('analytics', 'api.analytics', {'GET': operation('analyticsGet', 'Личный или групповой отчёт в пределах доступа',parameters=[query('circle','UUID кружка.',multiple=True,schema=UUID),CITY,TOPIC,query('problem_tag','Числовой ID тега задач.',multiple=True,schema=INT),query('worksheet_tag','Числовой ID тега листков.',multiple=True,schema=INT)],
    description='Текущее состояние уникальных пар школьник × задача. Для student — только личные данные, если другие роли не дают более широкого доступа.')}),
 ('invitations', 'api.invitations', {
    'GET': operation('invitationList', 'Мои приглашения; у администратора — все', 'inviter',parameters=[Q]),
    'POST': operation('invitationCreate', 'Создать приглашения по email', 'inviter',body=obj({'email':{'type':'string','format':'email'},'role':{'enum':['student','teacher','analyst','admin']},'circle_ids':ARRAY_UUID,'tags':ARRAY_INT},['email','role']),
        example={'email':'student@example.ru','role':'student','circle_ids':['<CIRCLE_UUID>']},status=201,
        description='Допустимая роль зависит от отправителя. Для student/teacher нужны circle_ids, для analyst — tags кружков, для admin область не передаётся. Ссылки хранятся в почтовой очереди, в ответе только id и ids.')}),
 ('invitations/<uuid:pk>', 'api.invitation_detail', {'DELETE': operation('invitationRevoke', 'Отозвать приглашение, не удаляя историю', 'inviter')}),
 ('accept/<str:token>', 'automation.invitation_accept', {
    'GET': operation('invitationPreview', 'Проверить ссылку приглашения без принятия', public=True),
    'POST': operation('invitationAccept', 'Явно принять приглашение', body=obj({'name':STRING,'password':STRING,'last_name':STRING,'first_name':STRING,'patronymic':STRING,'graduation_year':INT,'no_patronymic':BOOL}),
        description='Новый взрослый аккаунт: name и password. Школьники принимают приглашения на сайте. При добавлении student взрослому аккаунту обязательны last_name, first_name, patronymic, graduation_year и no_patronymic. Существующий получатель должен предъявить свой Bearer-токен или сессию. Не создаёт сеанс и токен; после регистрации используйте auth/token.',public=True)}),
 ('mailbox', 'api.mailbox', {'GET': operation('demoMailbox', 'Локальные письма с тестовыми ссылками', 'inviter',description='Только DEMO. Получателю реальные письма не отправляются. Не публикуйте токены приглашений.')}),
 ('users', 'api.users', {
    'GET': operation('userList', 'Найти аккаунты по ФИО/email/ID и фильтрам', 'admin',parameters=[Q,query('role','Роли.',multiple=True),query('state','Состояния.',multiple=True,schema={'enum':['active','inactive']}),query('graduation_year','Год выпуска.',multiple=True,schema=INT),query('meta','1 — ответ с пагинацией по 30 строк.',schema={'enum':['1']}),query('page','Страница.',schema=INT)]),
    'PATCH': operation('userRolesUpdate', 'Изменить роли и область аналитика', 'admin',body=obj({'id':INT,'roles':{'type':'array','items':{'enum':['student','teacher','analyst','admin']}},'tags':ARRAY_INT},['id','roles']),example={'id':12,'roles':['teacher','analyst'],'tags':[3]})}),
 ('documentation', 'api.documentation', {'GET': operation('documentationGet', 'Доступные инструкции для людей или ботов',parameters=[query('audience','Представление.',schema={'enum':['human','robot'],'default':'robot'}),query('download','markdown — выгрузка полного руководства.',schema={'enum':['markdown']})])}),
 ('documentation/<slug:section_id>', 'api.documentation', {'GET': operation('documentationSection', 'Один доступный раздел документации',parameters=[query('audience','Представление.',schema={'enum':['human','robot'],'default':'robot'})])}),
 ('openapi.json', 'api_reference.openapi', {'GET': operation('openapiGet', 'OpenAPI-схема операций, доступных вашим ролям')}),
]

RESPONSE_EXAMPLES = {
 'problemSearch':SEARCH_RESPONSE_EXAMPLE,'problemSearchText':SEARCH_RESPONSE_EXAMPLE,
 'tokenIssue': {'access_token':'<TOKEN_SHOWN_ONCE>','token_type':'Bearer','token':{'id':'<TOKEN_UUID>','name':'Мой бот','read_only':False,'expires_at':'2026-11-25T12:00:00+00:00','active':True},'user':{'id':12,'public_id':'U-12','roles':['teacher']}},
 'tokenCreate': {'access_token':'<TOKEN_SHOWN_ONCE>','token_type':'Bearer','token':{'id':'<TOKEN_UUID>','read_only':True,'active':True}},
 'circleList': [{'id':'<CIRCLE_UUID>','public_id':'C-12','name':'Математический кружок','city':'Москва','can_write':True}],
 'worksheetCopy': {'id':'<NEW_REVISION_UUID>','document_id':'<NEW_DOCUMENT_UUID>','public_id':'W-32','revision':1,'can_edit':True,'is_public':False,'problem_ids':['<PROBLEM_UUID>']},
 'worksheetUpdate': {'id':'<NEW_REVISION_UUID>','document_id':'<SAME_DOCUMENT_UUID>','public_id':'W-32','revision':2,'can_edit':True,'is_public':False},
 'issueCreate': [{'id':19,'issue_public_id':'ISS-19','public_id':'W-32','worksheet_id':'<REVISION_UUID>','document_id':'<DOCUMENT_UUID>','number':3,'issued_on':'2026-10-26'}],
 'journalMark': {'solved':True,'version':1},
 'invitationCreate': {'id':'<INVITATION_UUID>','ids':['<INVITATION_UUID>']},
 'topicCreate': {'id':'<TOPIC_UUID>','public_id':'TOP-42'},
 'tokenRevoke': {'ok':True}, 'tokenRevokeCurrent': {'ok':True},
}


def permitted(user, access):
    roles = set(user.roles)
    return access == 'all' or 'admin' in roles or bool(roles & {
        'writer': {'teacher'}, 'inviter': {'teacher','analyst'}, 'group': {'teacher','analyst'},
        'admin': set(), 'student': {'student'},
    }[access])


def operations_for(user, *, demo=False, read_only=False):
    from .people import has_adult_role
    if not has_adult_role(user):return []
    result = []
    for pattern, view, methods in ROUTES:
        for method, spec in methods.items():
            # Admin does not acquire student-only endpoints without the student role.
            if spec['access'] == 'student' and 'student' not in user.roles:
                continue
            if not permitted(user, spec['access']) or spec['id'] == 'demoMailbox' and not demo:
                continue
            if read_only and method not in {'GET','HEAD','OPTIONS'} and spec['id'] not in {'tokenIssue','tokenRevokeCurrent','problemSearchText'}:
                continue
            parameters = []
            for converter, name in re.findall(r'<(\w+):(\w+)>', pattern):
                schema = INT if converter == 'int' else UUID if converter == 'uuid' else STRING
                if name == 'kind':
                    schema = {'enum': ['solve','discussion','solution-visibility'] if spec['id'] == 'journalMark' else ['problem','worksheet']}
                if name == 'file_kind':
                    schema = {'enum': ['pdf','tex','project'] if set(user.roles)&{'teacher','admin'} else ['pdf']}
                parameters.append({'name':name,'in':'path','required':True,'schema':schema,
                                   'description':'Внутренний ID из ответа API; публичный P-/W-/C-ID сначала найдите через q.' if converter in {'uuid','int'} else name})
            result.append({**spec, **({'response_example':RESPONSE_EXAMPLES[spec['id']]} if spec['id'] in RESPONSE_EXAMPLES else {}), 'method':method,
                'path':'/api/v1/' + re.sub(r'<\w+:(\w+)>', r'{\1}', pattern),
                'parameters':parameters + spec['parameters']})
    return result
