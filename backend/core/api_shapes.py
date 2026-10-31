"""Readable request/response contracts for the existing API; no request execution."""
from copy import deepcopy


def text(description='', **extra):
    return {'type':'string', **({'description':description} if description else {}), **extra}


def number(description='', **extra):
    return {'type':'integer', **({'description':description} if description else {}), **extra}


def boolean(description=''):
    return {'type':'boolean', **({'description':description} if description else {})}


def record(title, properties, required=None, description=''):
    required=list(properties) if required is None else required
    return {'type':'object','title':title,'properties':properties,
            **({'required':list(required)} if required else {}),
            **({'description':description} if description else {})}


def array(items, description=''):
    return {'type':'array','items':items, **({'description':description} if description else {})}


def ref(name, description=''):
    return {'$ref':'#/components/schemas/'+name, **({'description':description} if description else {})}


def nullable(schema, description=''):
    return {'anyOf':[schema,{'type':'null'}], **({'description':description} if description else {})}


def alternatives(title, *variants):
    return {'title':title,'anyOf':list(variants)}


UUID=text('Внутренний UUID. Публичный ID вида C-12/P-12/W-12 используется для поиска.',format='uuid')
DATE=text('Календарная дата в формате YYYY-MM-DD.',format='date')
DATETIME=text('Дата и время ISO 8601 с часовым поясом.',format='date-time')
EMAIL=text('Email регистрации.',format='email')
PERCENT=nullable({'type':'number','minimum':0,'maximum':100},'Процент 0–100, округлённый до одного знака; null, если знаменатель равен нулю.')
ROLES=array(text('Код роли.',enum=['student','teacher','analyst','admin']),'Полный набор ролей аккаунта; права нескольких ролей объединяются.')
FREE={'description':'JSON-значение; структура зависит от вида события или ошибки.'}
EDUCATION={
 'graduation_year':nullable(number(minimum=1900,maximum=2200),'Ожидаемый год окончания 11-го класса, либо null.'),
 'current_grade':nullable(number(minimum=1,maximum=11),'Класс 1–11, вычисленный по учебному году; null вне этого диапазона.'),
 'grade_label':text('Подпись: «7 класс», «Выпускник», «Ещё не учится» или «Класс не указан».'),
}
FILES={
 'pdf_url':text('Относительный URL PDF. Передавайте тот же Bearer-токен при скачивании.'),
 'tex_url':text('Относительный URL единого TeX-исходника; доступен преподавателю/администратору.'),
 'project_url':text('Относительный URL ZIP многофайлового TeX-проекта; действуют права на исходники.'),
}
MATERIAL_BASE={
 'id':UUID,'public_id':text('Публичный P-ID задачи или W-ID логического листка.'),
 'title':text('Отображаемое название; у задачи без авторского названия формируется автоматически.'),
 'description':text('Дополнительное описание.'),'author':text('Имя автора.'),'archived':boolean('Материал архивирован.'),
 'topics':array(UUID,'Назначенные темы общего дерева.'),'tags':array(ref('Tag'),'Теги соответствующего справочника.'),**FILES,
}
PROBLEM={**MATERIAL_BASE,
 'custom_title':text('Авторское название; может быть пустым.'),'number':number('Локальный номер задачи, числовая часть P-ID.'),
 'source':text('Код источника; может быть пустым.'),'source_id':text('Номер на исходном сайте, независимый от P-ID.'),
 'source_url':text('Ссылка на источник.'),'attribution':record('Атрибуция источника',{
    'source':text('Код исходного источника.'),'source_id':text('Номер задачи в источнике.'),'url':text('Ссылка на исходную задачу.')},[],
    'Сведения о происхождении задачи. Пустой объект, если источник не задан.'),
 'statement':text('Условие обычным текстом.'),'statement_tex':text('TeX-фрагмент условия; пустая строка означает использование обычного текста.'),
 'source_format':text('Основной формат условия.',enum=['plain','tex']),
 'solution':text('Решение или ответ. Поле отсутствует, если аккаунту запрещено его видеть.'),
 'solution_tex':text('TeX-фрагмент решения; отсутствует вместе с закрытым решением.'),
 'solution_kind':text('Развёрнутое решение либо только ответ.',enum=['solution','answer']),
 'solved':boolean('Личная глобальная решённость. Добавляется в списке «Мои задачи».'),
}
WORKSHEET={**MATERIAL_BASE,
 'document_id':text('Стабильный UUID логического листка для редактирования и публикации.',format='uuid'),'author_id':number('Числовой ID аккаунта автора, не профиля преподавателя.'),
 'revision':number('Номер неизменяемой версии листка.',minimum=1),
 'is_public':boolean('Именно эта версия опубликована в общей библиотеке.'),
 'can_edit':boolean('Текущий пользователь может редактировать эту версию своего документа.'),
 'can_copy':boolean('Можно создать независимую личную копию.'),
 'can_publish':boolean('Можно опубликовать текущую версию для всех.'),
 'has_unpublished_changes':boolean('У документа есть изменения после опубликованной версии.'),
 'template_version':text('Версия шаблона сборки PDF/TeX.'),
 'problem_count':number('Количество задач.'),'problem_ids':array(UUID,'UUID задач в порядке листка.'),
}
ISSUE={
 'id':number('Числовой ID выдачи; это не UUID версии листка.'),
 'public_id':text('W-ID логического листка.'),'issue_public_id':text('Публичный ISS-ID выдачи.'),
 'worksheet_id':UUID,'document_id':UUID,'revision':number('Номер зафиксированной версии листка.'),
 'title':text('Название выданной версии.'),'description':text('Описание выданной версии.'),
 'tags':array(ref('Tag')),'circle_id':UUID,'circle_public_id':text('Публичный C-ID кружка.'),
 'circle_name':text('Название кружка.'),'city':text('Город кружка.'),
 'number':number('Порядковый номер выдачи внутри кружка.'),'issued_on':DATE,'problem_count':number('Количество задач.'),**FILES,
}
PERSON={
 'id':number('Числовой ID школьника, не аккаунта.'),'public_id':text('S-ID школьника.'),
 'user_public_id':text('U-ID аккаунта.'),'name':text('ФИО школьника.'),**EDUCATION,
}

SCHEMAS={
 'Error':record('Ошибка',{'detail':FREE},['detail'],'Ошибка валидации может содержать строку, массив или объект подробностей.'),
 'Ok':record('Подтверждение',{'ok':boolean('Действие выполнено.')},['ok']),
 'Tag':record('Тег',{
    'id':number('Числовой ID тега для входных массивов и фильтров.'),'public_id':text('Публичный TAG-ID.'),'name':text('Название тега.'),
    'kind':text('Справочник тега; возвращается в /tags.',enum=['problem','worksheet','circle']),
    'archived':boolean('Тег архивирован; возвращается в /tags.')},['id','public_id','name']),
 'User':record('Аккаунт',{
    'id':number('Числовой ID аккаунта.'),'public_id':text('Публичный U-ID.'),
    'student_public_id':nullable(text(),'S-ID профиля школьника; null, если профиля нет.'),
    'teacher_public_id':nullable(text(),'T-ID профиля преподавателя; null, если профиля нет.'),
    'name':text('Имя или полное ФИО.'),'email':EMAIL,'roles':ROLES,'is_active':boolean('Аккаунт действующий.'),
    'student_id':nullable(number(),'Числовой ID профиля школьника, если есть.'),**EDUCATION,
    'can_use_api':boolean('Есть роль преподавателя, аналитика или администратора.'),
    'last_name':text('Фамилия школьника.'),'first_name':text('Имя школьника.'),'patronymic':text('Отчество школьника; пусто при no_patronymic=true.'),
    'no_patronymic':boolean('Явно указано отсутствие отчества; только у профиля школьника.'),
    'profile_complete':boolean('ФИО и год выпуска заполнены по правилам регистрации школьника.'),
    'tags':array(number(),'Числовые ID тегов области аналитика; в ответах управления пользователями.')},
    ['id','public_id','name','email','roles','is_active','student_id']),
 'Token':record('Метаданные токена',{
    'id':UUID,'name':text('Название интеграции.'),'prefix':text('Безопасный префикс с многоточием; по нему нельзя восстановить секрет.'),
    'read_only':boolean('Разрешено только чтение, кроме отзыва текущего токена.'),'created_at':DATETIME,'expires_at':DATETIME,
    'last_used_at':nullable(DATETIME,'Последнее использование с точностью до интервала обновления 5 минут.'),
    'revoked_at':nullable(DATETIME,'Когда токен отозван; null, если не отозван.'),
    'active':boolean('Токен не истёк, не отозван и выпущен до текущего пароля.')},
    ['id','name','prefix','read_only','created_at','expires_at','last_used_at','revoked_at','active']),
 'TokenIssued':record('Созданный API-токен',{
    'access_token':text('Секрет. Возвращается один раз, только при выпуске; не сохраняйте в логах.'),
    'token_type':text('Тип заголовка авторизации.',const='Bearer'),'token':ref('Token'),'user':ref('User')},
    ['access_token','token_type','token','user']),
 'CircleTeacher':record('Преподаватель кружка',{
    'id':number('ID аккаунта преподавателя.'),'public_id':text('T-ID профиля преподавателя.'),
    'user_public_id':text('U-ID аккаунта.'),'name':text('Имя преподавателя.'),
    'email':nullable(EMAIL,'Email либо null, если роль не даёт доступ к групповым данным.')},['id','public_id','user_public_id','name','email']),
 'Circle':record('Кружок',{
    'id':UUID,'public_id':text('Публичный C-ID.'),'name':text('Название кружка.'),'description':text('Описание.'),
    'city':text('Город.'),'region':text('Регион.'),'archived':boolean('Кружок в архиве; редактирование запрещено.'),
    'tags':array(ref('Tag')),'teachers':array(ref('CircleTeacher'),'Действующие преподаватели.'),
    'student_count':number('Количество действующих школьников.'),'worksheet_count':number('Число выдач листков.'),
    'can_write':boolean('У текущего пользователя есть право изменять этот активный кружок.'),
    'can_analyse_group':boolean('Доступна групповая аналитика.'),'can_manage_teachers':boolean('Можно управлять назначениями преподавателей.')},
    ['id','public_id','name','description','city','region','archived','tags','teachers','student_count','worksheet_count','can_write','can_analyse_group','can_manage_teachers']),
 'Member':record('Школьник кружка',{**PERSON,'email':EMAIL},['id','public_id','user_public_id','name','graduation_year','current_grade','grade_label'],
    'Email возвращается только пользователю с правом редактирования кружка.'),
 'StudentSearch':record('Результат поиска школьника',{**PERSON,'email_hint':text('Маска email для различения однофамильцев.'),'already_enrolled':boolean('Школьник уже состоит в этом кружке.')},
    ['id','public_id','user_public_id','name','graduation_year','current_grade','grade_label','email_hint','already_enrolled']),
 'StudentUpdated':record('Год выпуска школьника',{'id':number(),'public_id':text(),**EDUCATION},['id','public_id','graduation_year','current_grade','grade_label']),
 'Problem':record('Задача',PROBLEM,['id','public_id','title','description','topics','tags','author','archived','statement','statement_tex','source_format','pdf_url','tex_url','project_url'],
    'Поля solution, solution_tex и solution_kind присутствуют только при разрешённом чтении решения.'),
 'Worksheet':record('Версия листка',WORKSHEET,['id','public_id','document_id','author_id','revision','is_public','can_edit','can_copy','can_publish','has_unpublished_changes','problem_count','problem_ids','topics','tags','pdf_url','tex_url','project_url'],
    'id — UUID этой версии, document_id — UUID логического листка. Для редактирования и публикации нужен document_id.'),
 'WorksheetDetail':record('Листок с задачами',{**WORKSHEET,'problems':array(ref('Problem'),'Задачи в порядке листка.'),'solutions_available':boolean('В листке есть хотя бы одно доступное решение.')},
    ['id','document_id','public_id','revision','problem_ids','problems','solutions_available']),
 'Issue':record('Выдача листка',ISSUE,['id','public_id','issue_public_id','worksheet_id','document_id','revision','circle_id','number','issued_on','pdf_url']),
 'IssueDetail':record('Выданная версия с задачами',{**WORKSHEET,**ISSUE,'problems':array(ref('Problem')),'solutions_available':boolean()},
    ['id','worksheet_id','document_id','revision','number','issued_on','problems','solutions_available'],
    'В этом ответе id — числовой ID выдачи. UUID зафиксированной версии находится в worksheet_id.'),
 'Solve':record('Решённость школьника',{'student_id':number(),'problem_id':UUID,'solved':boolean('Общая для всех кружков отметка.'),'version':number('Версия записи для следующего изменения.',minimum=0)},['student_id','problem_id','solved','version']),
 'Discussion':record('Разбор в кружке',{'problem_id':UUID,'discussed':boolean('Задача разобрана в данном кружке.'),'solution_visible':boolean('Разрешён показ решения школьникам кружка.'),'version':number('Общая версия записи разбора и видимости.',minimum=0)},['problem_id','discussed','solution_visible','version']),
 'JournalBlock':record('Блок листка в журнале',{
    'issue_id':number('ID выдачи.'),'issued_on':DATE,'number':number('Номер выдачи в кружке.'),
    'worksheet':record('Листок блока',{'id':UUID,'public_id':text(),'title':text(),'description':text(),**FILES},['id','public_id','title','description']),
    'problems':array(ref('Problem'))},['issue_id','issued_on','number','worksheet','problems']),
 'Journal':record('Журнал кружка',{
    'circle':record('Кружок журнала',{'id':UUID,'public_id':text(),'name':text()},['id','public_id','name']),
    'blocks':array(ref('JournalBlock'),'Задачи сгруппированы по выданным листкам.'),
    'people':array(record('Строка школьника',{**PERSON,'self':boolean('Строка текущего пользователя.')},['id','public_id','user_public_id','name','self'])),
    'solves':array(ref('Solve')),'discussions':array(ref('Discussion')),
    'can_write':boolean('Можно изменять отметки.'),'show_group_stats':boolean('Доступны групповые показатели.')},
    ['circle','blocks','people','solves','discussions','can_write','show_group_stats']),
 'MarkSolve':record('Результат изменения solve',{'solved':boolean(),'version':number('Новая версия записи.')},['solved','version']),
 'MarkDiscussion':record('Результат изменения discussion',{'discussed':boolean(),'solution_visible':boolean(),'version':number('Новая версия записи.')},['discussed','solution_visible','version']),
 'MarkVisibility':record('Результат изменения solution-visibility',{'solution_visible':boolean(),'version':number('Новая версия записи.')},['solution_visible','version']),
 'Topic':record('Тема',{'id':UUID,'public_id':text('TOP-ID.'),'name':text('Название темы.'),'parent_id':nullable(UUID,'UUID родителя; null для технического корня.'),
    'is_other':boolean('Системная терминальная тема «Прочее».'),'archived':boolean('Тема архивирована.'),'sort_order':number('Порядок среди соседних тем.')},
    ['id','public_id','name','parent_id','is_other','archived','sort_order']),
 'TopicCatalogue':record('Каталог тем',{'version':nullable(number(),'Версия снимка дерева.'),
    'metadata':nullable(record('Происхождение каталога',{'complete':boolean('Обход источника завершён.'),'generated_at':nullable(text()),'source_count':nullable(number())})),
    'topics':array(ref('Topic'))},['version','metadata','topics']),
 'Invitation':record('Приглашение',{'id':UUID,'public_id':text('INV-ID.'),'email':EMAIL,
    'role':text('Приглашаемая роль.',enum=['student','teacher','analyst','admin']),
    'circle':nullable(text(),'Название кружка; null для области по тегам или администратора.'),
    'delivery':nullable(record('Отправка письма',{'state':text(enum=['queued','retry','sent','failed','cancelled']),'attempts':number(),'error_code':text('Безопасный код ошибки, без SMTP-ответов или адресов.'),'sent_at':nullable(DATETIME)})),
    'circle_id':nullable(UUID),'state':text('Состояние приглашения.',enum=['pending','accepted','revoked','expired']),
    'expires_at':DATETIME,'created_at':DATETIME},['id','public_id','email','role','circle','circle_id','state','expires_at','created_at']),
 'InvitationCreated':record('Созданные приглашения',{'id':UUID,'ids':array(UUID,'Все созданные приглашения. Для каждого кружка отдельная ссылка.')},['id','ids']),
 'InvitationPreview':record('Проверка приглашения',{'email':EMAIL,'role':text(),'circle':nullable(text()),'registered':boolean('Аккаунт получателя уже существует.'),
    'student_profile_required':boolean('При принятии нужно передать полное ФИО и год выпуска.')},['email','role','circle','registered','student_profile_required']),
 'InvitationAccepted':record('Принятое приглашение',{'user':ref('User'),'accepted':boolean('Приглашение принято.')},['user','accepted']),
 'Mail':record('Письмо локальной демки',{'id':number(),'to':EMAIL,'subject':text('Тема письма.'),'token':text('Токен приглашения. Это не Bearer-токен; не публикуйте его.'),
    'role':text(),'circle':nullable(text()),'state':text(),'created_at':DATETIME},['id','to','subject','token','role','circle','state','created_at']),
 'AuditEvent':record('Событие истории',{'id':number(),'actor':text('Имя автора действия.'),'kind':text('Код события.'),'payload':{'type':'object','description':'Детали события зависят от kind.','additionalProperties':True},'created_at':DATETIME},['id','actor','kind','payload','created_at']),
}

# Account overview and analytics keep their role-specific nullable fields explicit.
SCHEMAS['Account']=record('Личный кабинет',{
 'user':ref('User'),'joined_at':DATETIME,'circle_count':number('Всего доступных кружков.'),'active_circle_count':number('Активных доступных кружков.'),
 'circles':array(record('Кружок в кабинете',{'id':UUID,'public_id':text(),'name':text(),'city':text(),'archived':boolean(),'relations':ROLES},['id','public_id','name','city','archived','relations']),'Первые 8 доступных кружков.'),
 'student':nullable(record('Личная сводка школьника',{'assigned':number(),'solved':number(),'remaining':number(),'percent':PERCENT,'active_circles':number()},['assigned','solved','remaining','percent','active_circles']),'null без роли школьника.'),
 'teacher':nullable(record('Сводка преподавателя',{key:number(description) for key,description in {
    'active_circles':'Активные кружки, которые ведёт аккаунт.','students':'Уникальные действующие школьники этих кружков.','issues':'Выдачи листков.',
    'problems_created':'Созданные задачи.','worksheets_created':'Созданные версии листков.'}.items()}),'null без роли преподавателя.'),
 'analyst':nullable(record('Область аналитика',{'active_circles':number(),'cities':number(),'tags':array(record('Тег области',{'tag__id':number(),'tag__name':text()},['tag__id','tag__name']))}),'null без роли аналитика.'),
 'admin':nullable(record('Общая сводка администратора',{key:number() for key in ['active_circles','active_users','problems','worksheets']}),'null без роли администратора.'),
 'pending_invitations':number('Непринятые действующие приглашения; поле отсутствует у аккаунта только с ролью школьника.')},
 ['user','joined_at','circle_count','active_circle_count','circles','student','teacher','analyst','admin'])
SCHEMAS['ProblemProgress']=record('Закрытие задачи',{
 'problem_id':UUID,'public_id':text('P-ID.'),'title':text(),'recipients':number('Уникальные получатели задачи в срезе.'),
 'solved':number('Уникальные получатели с отметкой «Решена».'),'remaining':number(),'percent':PERCENT,
 'circle_count':number(),'worksheet_count':number()},['problem_id','public_id','title','recipients','solved','remaining','percent','circle_count','worksheet_count'])
SCHEMAS['WorksheetProgress']=record('Прогресс листка',{
 'id':UUID,'public_id':text('W-ID.'),'title':text(),'pdf_url':FILES['pdf_url'],'recipients':number(),
 'problem_count':number('Задачи, оставшиеся после фильтров.'),'total_problem_count':number('Все задачи версии листка.'),
 'assigned':number('Назначенные пары школьник × задача.'),'solved':number(),'percent':PERCENT,
 'completed_recipients':number('Получатели, решившие все задачи этой версии, независимо от фильтра.'),'full_percent':PERCENT,
 'circle_count':number(),'issue_count':number()},['id','public_id','title','recipients','problem_count','total_problem_count','assigned','solved','percent','completed_recipients','full_percent','circle_count','issue_count'])
SCHEMAS['Analytics']=record('Аналитический отчёт',{
 'personal_only':boolean('В отчёте только личные назначения и результаты.'),'assigned_pairs':number('Уникальные назначенные пары школьник × задача.'),
 'solved_pairs':number('Решённые пары выбранного среза.'),'percent':PERCENT,'student_count':number(),'problem_count':number(),
 'rows':array(ref('ProblemProgress')),
 'counts':record('Сводные показатели',{
    **{key:number(desc) for key,desc in {
      'remaining_pairs':'Оставшиеся пары школьник × задача.','worksheet_count':'Разные версии листков.','issue_count':'Количество выдач.',
      'circle_count':'Кружки с назначениями.','full_worksheet_count':'Полностью закрытые пары получатель × листок.',
      'worksheet_recipient_count':'Все пары получатель × версия листка.','students_with_solves':'Школьники хотя бы с одним решением.',
      'students_without_solves':'Школьники без решений.','students_completed':'Школьники, решившие все назначенные задачи среза.'}.items()},
    'median_percent':PERCENT}),
 'discussion':nullable(record('Охват разбором',{'total':number('Пары кружок × задача.'),'discussed':number(),'remaining':number(),'visible':number('Открытые решения.'),'percent':PERCENT}), 'null без групповой аналитики.'),
 'distribution':array(record('Диапазон прогресса',{'label':text(),'count':number()}),'Пустой массив в личном отчёте.'),
 'worksheet_rows':array(ref('WorksheetProgress')),
 'student_rows':array(record('Результаты школьника',{**PERSON,'assigned':number(),'solved':number(),'remaining':number(),'percent':PERCENT}),'Пустой массив без группового доступа.'),
 'topic_rows':array(record('Результаты темы',{'id':nullable(UUID),'public_id':nullable(text()),'name':text(),'path':text('Полный путь темы.'),'depth':number(),
    'assigned':number(),'solved':number(),'recipients':number(),'problem_count':number(),'percent':PERCENT})),
 'circle_rows':array(record('Результаты кружка',{'id':UUID,'public_id':text(),'name':text(),'city':text(),'archived':boolean(),
    'recipients':number(),'worksheet_count':number(),'problem_count':number(),'assigned':number(),'solved':number(),'percent':PERCENT,'discussed':number(),'discussion_percent':PERCENT})),
 'attention':record('Требует внимания',{'unsolved_problem_count':number('Задачи без единого решения.'),'lowest_closure':array(ref('ProblemProgress'),'До 5 задач с наименьшим закрытием.'),
    'discussed_pending_problem_count':nullable(number(),'Разобранные задачи, по которым остались нерешённые назначения; null без группового доступа.')}),
 'definition':text('Определение единицы подсчёта.'),'computed_at':DATETIME,'topic_catalog_version':nullable(number(),'Версия снимка дерева тем.')},
 ['personal_only','assigned_pairs','solved_pairs','percent','student_count','problem_count','rows','counts','discussion','distribution','worksheet_rows','student_rows','topic_rows','circle_rows','attention','definition','computed_at','topic_catalog_version'])


def page(title, item, size=None, extra=None):
    return record(title,{'results':array(item),'count':number('Всего найдено записей.'),'page':number('Номер страницы с 1.'),
                        'page_size':number('Размер страницы.',**({'const':size} if size else {})),**(extra or {})},['results','count','page','page_size'])


MATERIAL_VARIANTS=alternatives('Задача или листок',ref('Problem'),ref('Worksheet'))
SCHEMAS['MaterialList']=alternatives('Список материалов или страница',
    {'title':'Массив, без pagination=1',**array(MATERIAL_VARIANTS)},
    page('Страница задач, pagination=1',ref('Problem')))
SCHEMAS['UsersList']=alternatives('Список пользователей или страница',
    {'title':'Массив, без meta=1',**array(ref('User'))},
    page('Страница, meta=1',ref('User'),30,{'graduation_years':array(number(),'Годы выпуска для фильтра.')}))
SCHEMAS['JournalIssue']=record('Журнал одного листка',{
    **SCHEMAS['Journal']['properties'],**SCHEMAS['JournalBlock']['properties']},
    SCHEMAS['Journal']['required']+SCHEMAS['JournalBlock']['required'])
SCHEMAS['MandatoryInstruction']=record('Обязательная инструкция робота',{
 'section_id':text('ID раздела; MUST прочитать перед применимым сценарием.'),'title':text(),
 'version':text('Версия обязательного контракта.'),'required':boolean('Всегда true: инструкция обязательна.'),
 'applies_when':text('any-api-workflow или worksheet-upload.'),
 'can_execute':boolean('Текущий аккаунт и режим токена допускают сценарий; false запрещает переход к записи.'),
 'url':text('URL инструкции с audience=robot, использовать тот же Bearer-токен.')})
SCHEMAS['GuideSection']=record('Раздел документации',{
 'id':text('Стабильное имя раздела.'),'required_for_robots':boolean('MUST соблюдать для применимого сценария.'),'instruction_version':text('Версия обязательной инструкции.'),'applies_when':text('Условие применения.'),'can_execute':boolean('Возможность выполнения с текущими правами и режимом токена.'),'category':text(),'title':text(),'summary':text(),'keywords':text(),
 'blocks':array(record('Блок инструкции',{
    'title':text(),'paragraphs':array(text()),'steps':array(text()),'bullets':array(text()),'formula':text(),'note':text(),
    'code':record('Пример кода',{'language':text(),'content':text()}),
    'table':record('Таблица',{'columns':array(text()),'rows':array(array(text()))})},['title'])),
 'links':array(record('Ссылка действия',{'label':text(),'href':text()})),
 'operations':array({'type':'object','description':'Метод, path, параметры, JSON-схема body, примеры и успешный статус; в версии для ботов.','additionalProperties':True})},
 ['id','category','title','summary','blocks','links'])
SCHEMAS['GuideCatalogue']=record('Доступная документация',{
 'instruction_policy_version':text('Версия обязательного контракта для роботов.'),'mandatory_instructions':array(ref('MandatoryInstruction'),'MUST прочитать все инструкции, применимые к запрошенному сценарию.'),
 'sections':array(ref('GuideSection')),'audience':text(enum=['human','robot']),'can_use_api':boolean('Есть право программного доступа.'),'api_base':text('Базовый путь /api/v1.'),
 'read_only_token':boolean('Текущий токен ограничен чтением.'),'markdown_url':text('URL скачивания руководства.'),'openapi_url':text('URL OpenAPI-схемы.')},
 ['sections','audience','api_base','read_only_token','markdown_url','openapi_url','instruction_policy_version','mandatory_instructions'])
SCHEMAS['Release']=record('Версия продукта и сборки',{'version':text('Версия продукта по SemVer.'),'status':text(enum=['development','released']),'revision':text('Git SHA, SHA-dirty либо unknown для архива без ревизии.')},['version','status','revision'])
SCHEMAS['OpenAPI']=record('Схема OpenAPI 3.1',{
 'x-plusfolio-release':ref('Release'),
 'openapi':text('Версия стандарта.'),'info':record('О сервисе',{'title':text(),'version':text(),'description':text()}),
 'servers':array(record('Базовый URL',{'url':text()})),'security':array({'type':'object','description':'Допустимые схемы аутентификации.'}),
 'paths':{'type':'object','description':'Ключи — пути; значения — описания доступных HTTP-методов.','additionalProperties':True},
 'components':{'type':'object','description':'Переиспользуемые JSON-схемы и схемы авторизации.','additionalProperties':True},
 'x-plusfolio-mandatory-instructions':record('Обязательный контракт роботов',{'policy_version':text(),'documentation_url':text(),'instructions':array(ref('MandatoryInstruction'))}),
 'externalDocs':record('Читаемый справочник',{'description':text(),'url':text()})},['openapi','info','servers','security','paths','components'])

SCHEMAS['Problem']['required']=[key for key in PROBLEM if key not in {'solution','solution_tex','solution_kind','solved'}]
SCHEMAS['Worksheet']['required']=list(WORKSHEET)
SCHEMAS['WorksheetDetail']['required']=[*WORKSHEET,'problems','solutions_available']
SCHEMAS['Issue']['required']=list(ISSUE)
SCHEMAS['IssueDetail']['required']=[*SCHEMAS['IssueDetail']['properties']]

SCHEMAS['ProblemSearch'] = record('Результаты поиска задач', {
 'results':array(record('Совпадение', {'problem':ref('Problem'),
    'match':text('Способ совпадения: identifier — ID; exact — нормализованный текст; text — текстовая близость; semantic — смысловая близость. Это не вероятность дубля.',enum=['identifier','exact','text','semantic']),
    'fields':array(text(enum=['statement','solution','metadata']),'Разрешённые поля совпадения: statement, solution или metadata (название и описание). При поиске ID массив может быть пустым.'),
    'excerpt':text('Фрагмент разрешённого условия или решения, до 500 символов; при поиске ID может быть пустым.')})),
 'semantic':boolean('true — в этом запросе участвовала модель. false также нормально для mode=text, ID, неготового индекса или недоступной модели; проверяйте notice.'),
 'pending':number('Количество доступных документов выбранных полей, ожидающих индексации, не число задач: условие и решение — разные документы.'),
 'notice':text('Пояснение неполного индекса или перехода на текстовый поиск. HTTP 200 с непустым notice остаётся успешным ответом. Пустая строка — ограничений не сообщено.')})

SCHEMAS['CatalogueSearch']=record('Поиск названий и описаний',{
 'kind':text(enum=['circle','worksheet','topic']),
 'results':array(record('Совпадение',{'entity':alternatives('Сущность согласно kind',ref('Circle'),ref('Worksheet'),ref('Topic')),
    'match':text(enum=['identifier','exact','text','semantic']),'excerpt':text('Разрешённое название/описание или полный путь темы, до 500 символов.')})),
 'semantic':boolean('Модель участвовала в запросе.'),'pending':number('Доступные документы без актуального вектора.'),
 'notice':text('Ограничения индексации или текстовый резервный поиск.')})

SCHEMAS['TexToolchain']=record('Точный контракт локальной TeX-сборки',{
 'contract_id':text('SHA-256 идентификатор исходников, шаблона, настроек и offline-ресурсов.'),
 'compiler':record('Компилятор',{'name':text(),'version':text(),'provider':text(),'arguments':array(text())}),
 'template_version':text('Версия шаблона сервиса.'),
 'files':{'type':'object','description':'Относительный путь в архиве → SHA-256. Проверить все файлы.','additionalProperties':{'type':'string'}},
 'archive_url':text('URL архива, скачивать с тем же Bearer-токеном.'),
 'archive_bytes_uncompressed':number('Общий размер файлов после распаковки.'),
 'prepare_command':text('Команда подготовки закреплённого компилятора.'),
 'preview_command':text('Команда сборки черновика без обращения к БД.'),
 'requirements':array(text()),
 'limits':record('Лимиты сервиса',{'wall_seconds':number(),'cpu_seconds':number(),'max_pdf_bytes':number(),
    'max_open_files':number(),'linux_address_space_bytes':number(),'max_problems':number()})})

RESPONSES={
 'catalogueSearch':ref('CatalogueSearch'),
 'texToolchain':ref('TexToolchain'),
 'problemSearch':ref('ProblemSearch'),'problemSearchText':ref('ProblemSearch'),
 'tokenIssue':ref('TokenIssued'),'tokenCreate':ref('TokenIssued'),'tokenList':array(ref('Token')),
 'tokenRevoke':ref('Ok'),'tokenRevokeCurrent':ref('Ok'),'passwordChange':ref('Ok'),
 'accountGet':ref('Account'),'accountUpdate':ref('Account'),
 'circleList':array(ref('Circle')),'circleCreate':ref('Circle'),'circleGet':ref('Circle'),'circleUpdate':ref('Circle'),
 'memberList':array(ref('Member')),'memberAdd':array(ref('Member')),'memberRemove':array(ref('Member')),
 'studentSearch':array(ref('StudentSearch')),'studentUpdate':ref('StudentUpdated'),'teacherAdd':ref('Circle'),'teacherRemove':ref('Circle'),
 'issueList':array(ref('Issue')),'issueCreate':array(ref('Issue')),'issueGet':ref('IssueDetail'),
 'journalGet':ref('Journal'),'journalIssueGet':ref('JournalIssue'),
 'journalMark':alternatives('Ответ зависит от kind',ref('MarkSolve'),ref('MarkDiscussion'),ref('MarkVisibility')),
 'circleAudit':array(ref('AuditEvent')),'materialList':ref('MaterialList'),'materialCreate':MATERIAL_VARIANTS,
 'materialGet':alternatives('Ответ зависит от kind',ref('Problem'),ref('WorksheetDetail')),
 'worksheetGet':ref('WorksheetDetail'),'worksheetUpdate':ref('WorksheetDetail'),'worksheetCopy':ref('WorksheetDetail'),'worksheetPublish':ref('WorksheetDetail'),
 'myMaterials':alternatives('Ответ зависит от kind',{'title':'kind=problem',**array(ref('Problem'))},{'title':'kind=worksheet',**array(ref('Issue'))}),
 'myProblem':ref('Problem'),'myIssue':ref('IssueDetail'),'topicList':ref('TopicCatalogue'),
 'topicCreate':record('Созданная тема',{'id':UUID,'public_id':text('TOP-ID.')},['id','public_id']),'topicUpdate':ref('Ok'),
 'tagList':array(ref('Tag')),'tagCreate':array(ref('Tag')),'analyticsGet':ref('Analytics'),
 'invitationList':array(ref('Invitation')),'invitationCreate':ref('InvitationCreated'),'invitationRevoke':ref('Ok'),
 'invitationPreview':ref('InvitationPreview'),'invitationAccept':ref('InvitationAccepted'),'demoMailbox':array(ref('Mail')),
 'userList':ref('UsersList'),'userRolesUpdate':array(ref('User')),
 'documentationGet':ref('GuideCatalogue'),'documentationSection':ref('GuideSection'),'openapiGet':ref('OpenAPI'),
}

DESCRIPTIONS={
 'tokenList':'Возвращает до 100 собственных токенов от новых к старым. Секреты и хеши не возвращаются; состояние active учитывает отзыв, срок и смену пароля.',
 'tokenCreate':'Создаёт дополнительный токен текущего аккаунта после проверки текущего пароля. Секрет доступен только в этом ответе; роли и назначения не меняются.',
 'tokenRevoke':'Отзывает личный токен по UUID. Чужой токен недоступен даже при известном UUID. Повторный отзыв безопасен.',
 'accountGet':'Возвращает собственный профиль и доступные ролевые сводки. Разделы student/teacher/analyst/admin равны null без соответствующей роли; список кружков ограничен первыми 8.',
 'circleList':'Возвращает только доступные аккаунту кружки, включая архивные. q ищет C-ID, название, город или регион; повторяющийся city задаёт несколько городов.',
 'circleCreate':'Создаёт кружок без обязательных школьников и преподавателей. Доступно администратору. Теги берутся из справочника кружков; участники и преподаватели назначаются отдельно.',
 'circleGet':'Возвращает сведения о кружке, действующих преподавателей и флаги can_write/can_analyse_group/can_manage_teachers для текущего пользователя.',
 'memberList':'Возвращает действующих школьников кружка с ФИО, ID и вычисленным классом. Email показывается только редактору кружка.',
 'memberRemove':'Завершает текущий период участия по email регистрации. Назначения листков и решения сохраняются. В ответе — обновлённый список действующих школьников.',
 'studentUpdate':'Изменяет общий год выпуска действующего школьника своего активного кружка. Текущий класс пересчитывается; изменение отражается во всех кружках школьника.',
 'teacherRemove':'Завершает назначение преподавателя в этом кружке. Данные и назначения других преподавателей сохраняются. Доступно администратору; ответ — обновлённый кружок.',
 'issueList':'Возвращает выдачи выбранного кружка от новых к старым. Каждая запись содержит фиксированную версию, дату, стабильный номер в кружке и ссылки на документы.',
 'issueGet':'Открывает конкретную уже выданную версию, а не текущую редакцию автора. Числовое поле id относится к выдаче; UUID версии находится в worksheet_id.',
 'issueFile':'Формирует документ зафиксированной выдачи с названием кружка, датой и номером. solutions=1 добавляет только разрешённые решения; TeX и ZIP требуют роль преподавателя или администратора.',
 'journalGet':'Возвращает школьников, блоки задач выбранных листков, глобальные решения и локальные разборы. Отсутствующая запись отметки означает false с ожидаемой версией 0.',
 'journalIssueGet':'Возвращает журнал одной выдачи. Для совместимости данные первого блока дополнительно присутствуют на верхнем уровне ответа.',
 'journalExport':'Скачивает срез журнала по выдачам и поиску школьника. Формат по умолчанию XLSX; TSV сохраняет данные без оформления. Это файл, а не JSON.',
 'circleAudit':'Возвращает последние 100 событий кружка от новых к старым. Доступно преподавателям этого кружка, аналитикам в своей области и администратору.',
 'materialList':'Возвращает доступные задачи либо версии листков по kind. Без постраничного режима — до 300 записей. Для задач pagination=1 включает results/count; scope применяется к листкам, all доступен только администратору.',
 'materialGet':'Открывает доступную задачу или неизменяемую версию листка. Поля решения отсутствуют без разрешения. Необязательный circle задаёт контекст кружка для видимости решения.',
 'materialFile':'Формирует документ доступного материала. Для библиотечного листка используются заглушки даты, кружка и номера. Решения фильтруются по правам, исходники доступны преподавателю и администратору.',
 'worksheetGet':'Открывает доступную текущую личную или опубликованную версию по стабильному document_id. Возвращает автора, revision, задачи и флаги разрешённых действий.',
 'worksheetPublish':'Выбирает текущую версию как общую библиотечную. Только администратор, в том числе для чужого личного листка. version должен совпадать с revision; старые выдачи не меняются.',
 'myProblem':'Открывает только назначенную текущему школьнику задачу. Разрешения на решения объединяются по его действующим кружкам; решённость сама по себе решение не открывает.',
 'myIssue':'Открывает назначенную школьнику выдачу, в том числе из прежнего кружка. Возвращает фиксированный состав и ссылки на документы именно этой выдачи.',
 'myIssueFile':'Скачивает документ назначенной текущему школьнику выдачи. Показ решений проверяется заново; доступ к TeX/ZIP дополнительно требует роль преподавателя или администратора.',
 'topicCreate':'Добавляет обычную тему под действующим несистемным родителем и автоматически создаёт внутри неё терминальную «Прочее». Доступно администратору.',
 'topicUpdate':'Меняет название, родителя или архивное состояние обычной темы. Системные узлы защищены, циклы запрещены; старые материалы сохраняют свои связи.',
 'tagList':'Возвращает теги всех трёх справочников с полями kind и archived. Для формы выберите записи нужного вида; q поддерживает TAG-ID и название.',
 'tagCreate':'Создаёт тег в выбранном справочнике и возвращает обновлённый список тегов. Доступно администратору; повтор имени в том же справочнике даёт конфликт.',
 'invitationList':'Возвращает до 100 отправленных вами приглашений; администратор видит все. Истёкшая ожидающая ссылка показывается со state=expired. Сами токены ссылок здесь не возвращаются.',
 'invitationRevoke':'Отзывает ссылку приглашения. Это не отзыв уже выданной роли или участия; действующий доступ прекращается через назначения или управление ролями.',
 'invitationPreview':'Проверяет срок и полномочия отправителя, возвращает адресата и требования к регистрации. Просмотр не принимает приглашение и не выдаёт права.',
 'userList':'Возвращает аккаунты и их роли только администратору. q поддерживает ФИО/email/ID. meta=1 включает страницы по 30 записей и варианты года выпуска; без meta список ограничен 300.',
 'userRolesUpdate':'Заменяет полный набор ролей и тегов области аналитика указанного аккаунта. Снятие teacher/student завершает соответствующие назначения. Последнего администратора лишить этой роли нельзя.',
 'documentationGet':'Возвращает все разделы, доступные текущим ролям, в представлении human или robot. download=markdown возвращает текстовый файл вместо JSON.',
 'documentationSection':'Возвращает один раздел по его стабильному имени. Закрытый и отсутствующий раздел одинаково возвращают 404.',
 'openapiGet':'Возвращает машиночитаемый контракт API, из которого строится этот справочник. Методы отобраны по текущим ролям и режиму токена; реальные данные пользователей в схему не входят.',
}


def parameter_description(operation_id, parameter):
    if parameter.get('in')!='path':return parameter.get('description','')
    name=parameter['name']
    if name=='pk':
        if operation_id in {'tokenRevoke'}:return 'UUID собственного API-токена из списка /auth/tokens.'
        if operation_id.startswith('worksheet') and operation_id!='worksheetCopy':return 'Стабильный document_id листка, не UUID его версии.'
        if operation_id=='worksheetCopy':return 'UUID исходной неизменяемой версии листка: id материала или worksheet_id выдачи.'
        if operation_id.startswith('material'):return 'UUID задачи либо UUID версии листка, в зависимости от kind.'
        if operation_id=='myProblem':return 'UUID назначенной вам задачи.'
        if operation_id=='topicUpdate':return 'UUID обычной темы.'
        if operation_id=='invitationRevoke':return 'UUID приглашения из списка /invitations.'
        return 'UUID доступного кружка из /circles. Публичный C-ID сначала найдите через q.'
    return {
        'student_id':'Числовой ID профиля школьника. Не подставляйте U-ID аккаунта.',
        'issue_id':'Числовой ID выдачи, не UUID версии и не порядковый номер листка в кружке.',
        'problem_id':'UUID задачи, выданной этому кружку.',
        'file_kind':'Вид документа: pdf; tex и project (ZIP) доступны преподавателю/администратору.',
        'token':'Секрет ссылки приглашения. Это не Bearer-токен авторизации.',
        'section_id':'Имя раздела документации, например worksheet-copies или api-access.',
        'kind':'Вид отметки: solve, discussion, solution-visibility.' if operation_id=='journalMark' else 'Вид материала: problem — задача, worksheet — листок.',
    }.get(name,parameter.get('description',''))

FIELD_DESCRIPTIONS={
 'login':'Email регистрации владельца аккаунта.','password':'Пароль аккаунта. Не сохраняйте в логах.',
 'current_password':'Действующий пароль аккаунта.','new_password':'Новый пароль, не менее 12 символов.','confirm_password':'Точное повторение нового пароля.',
 'name':'Имя или название. Для школьника — полные фамилия, имя и отчество.',
 'email':'Email регистрации. В назначении преподавателя также допускается T-ID или U-ID.',
 'title':'Название. У листка не должно быть пустым; у задачи может быть пустым.','description':'Необязательное дополнительное описание.',
 'city':'Город кружка.','region':'Регион кружка.','tags':'Числовые ID готовых тегов соответствующего справочника.',
 'topics':'UUID действующих тем общего дерева. Минимум одна тема для материала.',
 'statement':'Условие задачи обычным текстом. Если пусто, нужен statement_tex.',
 'solution':'Решение обычным текстом. Если пусто, нужен solution_tex.',
 'statement_tex':'TeX-фрагмент условия без преамбулы; можно использовать TikZ.',
 'solution_tex':'TeX-фрагмент решения без преамбулы.',
 'problems':'Непустой массив UUID задач без повторов; порядок массива задаёт порядок в листке.',
 'version':'Ожидаемая версия из последнего чтения. При конфликте сервер вернёт 409.',
 'value':'Новое состояние отметки: строго true или false.',
 'student_id':'Числовой ID профиля школьника, не ID аккаунта.',
 'graduation_year':'Год окончания 11-го класса: целое число 1900–2200.',
 'no_patronymic':'true, если у школьника нет отчества. Иначе false.',
 'worksheet_ids':'UUID выбранных неизменяемых версий листков, а не document_id. От 1 до 300.',
 'issued_on':'Дата выдачи YYYY-MM-DD, не позднее сегодняшней по московскому времени.',
 'circle_ids':'UUID кружков для отдельных приглашений. От 1 до 300.',
 'role':'Выдаваемая роль; сервер проверяет иерархию и область отправителя.',
 'roles':'Полный новый набор ролей аккаунта. Хотя бы одна роль.',
 'parent_id':'UUID родительской обычной темы. Циклы и вложенность в «Прочее» запрещены.',
 'archived':'Архивировать обычную ветку тем; системные темы защищены.',
 'kind':'Тип сущности или справочник. Не смешивайте теги задач, листков и кружков.',
 'id':'Числовой внутренний ID аккаунта из результата поиска.',
 'expires_in_days':'Срок действия токена, целое число от 1 до 90. По умолчанию 30.',
 'read_only':'true — только чтение и отзыв текущего токена; false — изменения в пределах прав аккаунта.',
}


def request_schema_for(operation_id, schema):
    if schema is None:
        return None
    result=deepcopy(schema)
    def annotate(value):
        for name, original in list(value.get('properties',{}).items()):
            # Registry fields intentionally reuse primitive schema objects. Detach each
            # property before adding a field-specific description.
            field=deepcopy(original)
            value['properties'][name]=field
            field.setdefault('description',FIELD_DESCRIPTIONS.get(name,'Значение поля '+name+'.'))
            if name in {'password','current_password','new_password','confirm_password'}:
                field['writeOnly']=True
            annotate(field)
    annotate(result)
    if operation_id in {'tokenIssue','tokenCreate'}:
        result['properties']['name']['description']='Название интеграции, от 1 до 100 символов.'
    if operation_id=='memberAdd':
        result['description']='Передайте ровно одно: email зарегистрированного школьника либо student_id из подсказок.'
    if operation_id=='accountUpdate':
        result['description']='При совмещении со student обязательны last_name, first_name, patronymic, graduation_year и no_patronymic. Для остальных — только name.'
    if operation_id=='materialCreate':
        result['description']='kind=problem: условие и решение в тексте или TeX. kind=worksheet: непустые title и problems. Для обоих видов обязателен непустой topics.'
    if operation_id=='worksheetUpdate':
        result['description']='Передайте version и только изменяемые поля. Пропущенные значения сохраняются из текущей версии листка.'
    if operation_id=='invitationCreate':
        result['description']='student/teacher: нужны circle_ids. analyst: нужны tags кружков. admin: область не передаётся.'
    if operation_id=='invitationAccept':
        result['description']='Новый взрослый аккаунт: name и password. Школьники регистрируются на сайте. При добавлении student взрослому аккаунту обязательны last_name, first_name, patronymic, graduation_year и no_patronymic. Существующий получатель входит под своим аккаунтом.'
    if operation_id=='journalMark':
        result['description']='kind=solve: обязателен student_id. Для discussion и solution-visibility он не нужен. version всегда относится к изменяемой записи.'
    return result


def response_schema_for(operation_id):
    if operation_id not in RESPONSES:
        raise ValueError('Missing response contract: '+operation_id)
    return deepcopy(RESPONSES[operation_id])


def reachable_schemas(document):
    """Include only definitions referenced by the permission-filtered operations."""
    found=set()
    def visit(value):
        if isinstance(value,dict):
            target=value.get('$ref','')
            if target.startswith('#/components/schemas/'):
                name=target.rsplit('/',1)[-1]
                if name not in found:
                    found.add(name);visit(SCHEMAS[name])
            for item in value.values():visit(item)
        elif isinstance(value,list):
            for item in value:visit(item)
    visit(document)
    return {name:deepcopy(SCHEMAS[name]) for name in sorted(found)}
